import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz
from tuya_connector import TuyaOpenAPI

# --- 1. PAGE CONFIG & MIDNIGHT GLASS CSS ---
st.set_page_config(page_title="Power Command", page_icon="⚡", layout="centered")

st.markdown("""
    <style>
    /* MIDNIGHT GRADIENT BACKGROUND */
    .stApp {
        background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
        background-attachment: fixed;
    }
    
    /* GLASSMORPHISM CARDS */
    div[data-testid="stMetric"], div[data-testid="stExpander"], div.stContainer {
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 20px;
        padding: 20px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        color: white;
    }
    
    /* TYPOGRAPHY */
    h1, h2, h3, p, div, span, label {
        color: #ffffff !important;
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }
    h1 { font-weight: 700; text-shadow: 0 0 10px rgba(0,255,255,0.5); }
    
    /* PILL BUTTONS */
    div.stButton > button {
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%);
        color: white;
        border: none;
        border-radius: 30px;
        height: 3.5em;
        font-weight: 600;
        width: 100%;
        transition: all 0.3s ease;
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(75, 108, 183, 0.6);
    }
    div.stButton > button[kind="secondary"] {
        background: linear-gradient(90deg, #eb3349 0%, #f45c43 100%);
    }

    /* METRIC VALUES */
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        background: -webkit-linear-gradient(#00c6ff, #0072ff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
    }
    
    #MainMenu, footer, header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. PASSWORD PROTECTION ---
def check_password():
    if st.session_state.get("password_correct", False): return True
    def password_entered():
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
    st.text_input("🔒 Login", type="password", on_change=password_entered, key="password")
    return False

if not check_password(): st.stop()

# --- 3. CONFIGURATION & KEYS ---
REGION = "SE3"
TUYA_ACCESS_ID = "qdqkmyefdpqav3ckvnxm"      
TUYA_ACCESS_SECRET = "c1b019580ece45a2902c9d0df19a8e02"     
TUYA_ENDPOINT = "https://openapi.tuyaeu.com"

HOUSES = {
    "Main House": {"has_smart_devices": False, "plug_id": "", "heater_id": ""},
    "Guest House": {"has_smart_devices": True, "plug_id": "364820008cce4e2efeda", "heater_id": "bf070e912f4a1df81dakvu"}
}

# 2026 Estimated Fees (Öre/kWh)
ENERGY_TAX_INC_VAT = 46.00 
ELLEVIO_TRANSFER_INC_VAT = 8.75 
FORTUM_FEE_INC_VAT = 0.74 

# Power consumption mapping for the heater levels
LEVEL_WATTS = {
    "low": 750,
    "middle": 1250,
    "high": 2000
}

def get_total_price_per_kwh(spot_price_ore_ex_vat):
    # (Spot + Fortum Fee) + 25% VAT + Ellevio Transfer + Energy Tax
    elec_inc_vat = (spot_price_ore_ex_vat * 1.25) + FORTUM_FEE_INC_VAT
    return elec_inc_vat + ENERGY_TAX_INC_VAT + ELLEVIO_TRANSFER_INC_VAT

# --- 4. TUYA API FUNCTIONS ---
def get_tuya_status(device_id):
    if not device_id: return None
    try:
        openapi = TuyaOpenAPI(TUYA_ENDPOINT, TUYA_ACCESS_ID, TUYA_ACCESS_SECRET)
        openapi.connect()
        response = openapi.get(f'/v1.0/devices/{device_id}/status')
        return response['result'] if response['success'] else None
    except: return None

def send_tuya_command(device_id, code, value):
    try:
        openapi = TuyaOpenAPI(TUYA_ENDPOINT, TUYA_ACCESS_ID, TUYA_ACCESS_SECRET)
        openapi.connect()
        commands = {'commands': [{'code': code, 'value': value}]}
        openapi.post(f'/v1.0/devices/{device_id}/commands', commands)
        return True
    except: return False

# --- 5. PRICE DATA FETCHING ---
@st.cache_data(ttl=900)
def fetch_hourly_prices():
    tz = pytz.timezone('Europe/Stockholm')
    today = datetime.now(tz)
    dates = [today, today + timedelta(days=1)]
    all_data = []
    
    for date_obj in dates:
        date_str = date_obj.strftime("%Y/%m-%d")
        url = f"https://www.elprisetjustnu.se/api/v1/prices/{date_str}_{REGION}.json"
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200: all_data.extend(r.json())
        except: pass
            
    if not all_data: return None, None

    rows = []
    for hour in all_data:
        start = datetime.fromisoformat(hour['time_start'])
        spot_ore = hour['SEK_per_kWh'] * 100 
        total_ore = get_total_price_per_kwh(spot_ore)
        
        if total_ore < 150: color = "#00c6ff"
        elif total_ore < 250: color = "#0072ff"
        else: color = "#f45c43"

        rows.append({
            "Time": start, 
            "Total Price": round(total_ore, 2), 
            "Color": color
        })
    return pd.DataFrame(rows), datetime.now(tz)

# --- 6. MAIN APP LOGIC ---
st.title("Smart Home")

selected_house_name = st.selectbox("Select Property", list(HOUSES.keys()))
config = HOUSES[selected_house_name]

df, last_updated = fetch_hourly_prices()

# Device State Variables
live_power_w = 0.0
current_temp = 0
target_temp = 20
heater_on = False
heater_level = "middle"

if config["has_smart_devices"]:
    # Get Plug Info
    p_status = get_tuya_status(config["plug_id"])
    if p_status:
        for i in p_status:
            if i['code'] == 'cur_power': live_power_w = i['value'] / 10.0
    
    # Get Heater Info
    h_status = get_tuya_status(config["heater_id"])
    if h_status:
        for i in h_status:
            if i['code'] == 'temp_current': current_temp = i['value']
            if i['code'] == 'temp_set': target_temp = i['value']
            if i['code'] == 'switch': heater_on = i['value']
            if i['code'] == 'level': heater_level = i['value']

# Calculate Current Price
tz = pytz.timezone('Europe/Stockholm')
now = datetime.now(tz)
current_total_price = 0.0
if df is not None:
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    if not current_row.empty:
        current_total_price = current_row.iloc[0]['Total Price']

# --- SECTION 1: DYNAMIC METRICS ---
c1, c2 = st.columns(2)
with c1:
    st.metric("Total Rate", f"{current_total_price:.2f} öre", "Incl. Tax/Fees")

with c2:
    if config["has_smart_devices"]:
        # If the heater is OFF, force 0. Otherwise, use the higher of sensor vs level-preset
        if not heater_on:
            calc_watts = 0
        else:
            preset_watts = LEVEL_WATTS.get(heater_level, 1000)
            calc_watts = live_power_w if live_power_w > 50 else preset_watts
        
        cost_hourly = (calc_watts / 1000.0) * (current_total_price / 100.0)
        st.metric("Live Cost", f"{cost_hourly:.2f} kr/h", f"{calc_watts}W Actual")
    else:
        st.metric("Consumption", "--", "No Sensor")

# --- SECTION 2: PRICE CHART ---
if df is not None:
    st.write("### 24h Price Forecast")
    df['Opacity'] = df['Time'].apply(lambda x: 1.0 if x.hour == now.hour and x.date() == now.date() else 0.4)
    chart = alt.Chart(df[df['Time'] >= now - timedelta(hours=2)]).mark_bar(cornerRadius=5).encode(
        x=alt.X('Time:T', axis=alt.Axis(format='%H:%M', title=None, labelColor='white')),
        y=alt.Y('Total Price:Q', axis=alt.Axis(title=None, labelColor='white')),
        color=alt.Color('Color:N', scale=None),
        opacity=alt.Opacity('Opacity:Q', legend=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=200).configure_view(strokeWidth=0).configure_axis(grid=False)
    st.altair_chart(chart, use_container_width=True)

# --- SECTION 3: CLIMATE CONTROL PANEL ---
if config["has_smart_devices"]:
    st.write("### Heater Control")
    with st.container():
        # Status Row
        m1, m2, m3 = st.columns(3)
        m1.metric("Room", f"{current_temp}°")
        m2.metric("Target", f"{target_temp}°")
        m3.metric("Mode", heater_level.upper())

        # Power Level Toggles
        st.write("Set Power Level:")
        l1, l2, l3 = st.columns(3)
        with l1:
            if st.button("LOW"):
                send_tuya_command(config["heater_id"], 'level', 'low'); st.rerun()
        with l2:
            if st.button("MED"):
                send_tuya_command(config["heater_id"], 'level', 'middle'); st.rerun()
        with l3:
            if st.button("HIGH"):
                send_tuya_command(config["heater_id"], 'level', 'high'); st.rerun()

        st.markdown("---")
        
        # Temp and On/Off Row
        b1, b2, b3 = st.columns([1, 1, 1.5])
        with b1:
            if st.button("Temp -1°"):
                send_tuya_command(config["heater_id"], 'temp_set', target_temp - 1); st.rerun()
        with b2:
            if st.button("Temp +1°"):
                send_tuya_command(config["heater_id"], 'temp_set', target_temp + 1); st.rerun()
        with b3:
            label = "STOP HEATER" if heater_on else "START HEATER"
            if st.button(label, type="primary" if not heater_on else "secondary"):
                send_tuya_command(config["heater_id"], 'switch', not heater_on); st.rerun()

# Footer
st.markdown("---")
if st.button("🔄 Force Data Refresh"):
    st.cache_data.clear()
    st.rerun()
