import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz
from tuya_connector import TuyaOpenAPI

# --- 1. PAGE CONFIG & DARK MODERN CSS ---
st.set_page_config(page_title="Power Monitor", page_icon="⚡", layout="centered")

# Custom CSS for "Cyberpunk/Modern Dark" Look
st.markdown("""
    <style>
    /* Force Dark Background */
    .stApp {
        background-color: #0E1117;
    }
    
    /* Modern Card Styling (Dark Glass) */
    div[data-testid="stMetric"], div[data-testid="stExpander"] {
        background-color: #262730;
        border: 1px solid #41424C;
        border-radius: 12px;
        padding: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s;
    }
    
    div[data-testid="stMetric"]:hover {
        border-color: #00E676; /* Neon Green Glow on Hover */
    }

    /* Text Colors */
    h1, h2, h3, p, div, span, label {
        color: #FAFAFA !important;
        font-family: 'Segoe UI', sans-serif;
    }
    
    /* Neon Accents for Metrics */
    div[data-testid="stMetricValue"] {
        font-weight: 700; 
    }
    
    /* Buttons */
    div.stButton > button {
        background-color: #262730;
        color: white;
        border: 1px solid #41424C;
        border-radius: 8px;
        height: 3em;
    }
    div.stButton > button:hover {
        border-color: #00E676;
        color: #00E676;
    }
    
    /* Hide Header/Footer */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. PASSWORD PROTECTION ---
def check_password():
    if st.session_state.get("password_correct", False): return True
    def password_entered():
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
    st.text_input("🔒 Enter Password", type="password", on_change=password_entered, key="password")
    return False

if not check_password(): st.stop()

# --- 3. CONFIG & HOUSE SETUP ---
REGION = "SE3"
TUYA_ACCESS_ID = "qdqkmyefdpqav3ckvnxm"      
TUYA_ACCESS_SECRET = "c1b019580ece45a2902c9d0df19a8e02"     
TUYA_ENDPOINT = "https://openapi.tuyaeu.com"

# Dictionary to handle multiple properties
HOUSES = {
    "Guest House": {
        "plug_id": "364820008cce4e2efeda",
        "heater_id": "bf070e912f4a1df81dakvu",
        "has_smart_devices": True
    },
    "Main House": {
        "plug_id": "", 
        "heater_id": "",
        "has_smart_devices": False 
    }
}

# --- EXACT FEE CALIBRATION (VERIFIED) ---
GRID_TOTAL_INC_VAT = 61.13  
FORTUM_ADDONS_EX_VAT = 15.57 

def get_total_price_per_kwh(spot_price_ore_ex_vat):
    electricity_part_inc_vat = (spot_price_ore_ex_vat + FORTUM_ADDONS_EX_VAT) * 1.25
    total_price = electricity_part_inc_vat + GRID_TOTAL_INC_VAT
    return total_price

# --- TUYA CONNECT ---
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

# --- FETCH PRICES ---
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
        
        # VISIBILITY COLORS (Neon Traffic Light)
        if total_ore < 100: color = "#00E676"   # Neon Green (Cheap)
        elif total_ore < 200: color = "#FFEA00" # Bright Yellow (Caution)
        else: color = "#FF1744"                 # Neon Red (Expensive)

        rows.append({
            "Time": start, 
            "Hour": start.hour,
            "Total Price": round(total_ore, 2), 
            "Spot Price": round(spot_ore, 2),
            "Color": color
        })
    
    df = pd.DataFrame(rows)
    df.drop_duplicates(subset=['Time'], inplace=True)
    return df, datetime.now(tz)

# --- MAIN DASHBOARD UI ---
st.title("⚡ Power Command")

# 1. PROPERTY SELECTOR
selected_house_name = st.selectbox("Select Property", list(HOUSES.keys()))
current_house_config = HOUSES[selected_house_name]

# 2. Fetch Data
if current_house_config["has_smart_devices"]:
    plug_status = get_tuya_status(current_house_config["plug_id"])
    heater_status = get_tuya_status(current_house_config["heater_id"])
else:
    plug_status = None
    heater_status = None

df, last_updated = fetch_hourly_prices()

# 3. Parse Devices
live_power_w = 0.0
if plug_status:
    for i in plug_status:
        if i['code'] == 'cur_power': live_power_w = i['value'] / 10.0

current_temp = 0; target_temp = 20; heater_on = False
if heater_status:
    for i in heater_status:
        if i['code'] == 'temp_current': current_temp = i['value']
        if i['code'] == 'temp_set': target_temp = i['value']
        if i['code'] == 'switch': heater_on = i['value']

# 4. TOP SECTION: KEY METRICS
tz = pytz.timezone('Europe/Stockholm')
now = datetime.now(tz)
current_price_ore = 0.0

if df is not None:
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    if not current_row.empty:
        current_price_ore = current_row.iloc[0]['Total Price']

    # GRID LAYOUT FOR METRICS
    c1, c2 = st.columns(2)
    with c1:
        st.metric(
            label="💰 LIVE PRICE", 
            value=f"{current_price_ore:.0f} öre",
            delta="Exact Rate (Inc. Fees)",
            delta_color="off"
        )
    with c2:
        if current_house_config["has_smart_devices"]:
            cost_now = (live_power_w / 1000.0) * (current_price_ore / 100.0)
            st.metric(
                label="⚡ LIVE CONSUMPTION", 
                value=f"{live_power_w:.0f} W",
                delta=f"{cost_now:.2f} kr / hour",
                delta_color="inverse"
            )
        else:
            st.metric(label="⚡ LIVE CONSUMPTION", value="-- W", delta="No Sensor Linked", delta_color="off")

    # CHART SECTION
    st.markdown("---")
    st.caption(f"Price Forecast (Next 24h) • Current: {now.strftime('%H:%M')}")
    
    # Active Bar Highlighting
    df['Opacity'] = df['Time'].apply(lambda x: 1.0 if x.hour == now.hour and x.date() == now.date() else 0.3)
    
    chart = alt.Chart(df[df['Time'] >= now - timedelta(hours=2)]).mark_bar(cornerRadius=4).encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M', title=None, domain=False, tickSize=0, labelColor='#888')),
        y=alt.Y('Total Price', axis=alt.Axis(title=None, domain=False, tickSize=0, labelColor='#888')),
        color=alt.Color('Color', scale=None),
        opacity=alt.Opacity('Opacity', legend=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=200).configure_view(strokeWidth=0).configure_axis(grid=False)
    
    st.altair_chart(chart, use_container_width=True)

# 5. HEATER CONTROL SECTION
if current_house_config["has_smart_devices"]:
    st.markdown("### 🔥 Climate Control")
    if heater_status:
        # Status Row
        c_temp, c_targ, c_stat = st.columns(3)
        with c_temp: st.metric("Indoors", f"{current_temp}°")
        with c_targ: st.metric("Target", f"{target_temp}°")
        with c_
