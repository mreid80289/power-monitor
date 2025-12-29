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
        background-color: #1E1E24;
        border: 1px solid #31333F;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    
    /* Text Colors */
    h1, h2, h3, p, div, span, label {
        color: #FAFAFA !important;
        font-family: 'Segoe UI', sans-serif;
    }
    
    /* Buttons */
    div.stButton > button {
        background-color: #262730;
        color: white;
        border: 1px solid #41424C;
        border-radius: 8px;
    }
    div.stButton > button:hover {
        border-color: #00E676;
        color: #00E676;
    }
    
    /* Tab Styling */
    button[data-baseweb="tab"] {
        background-color: transparent !important;
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

HOUSES = {
    "Main House": {"has_smart_devices": False, "plug_id": "", "heater_id": ""},
    "Guest House": {"has_smart_devices": True, "plug_id": "364820008cce4e2efeda", "heater_id": "bf070e912f4a1df81dakvu"}
}

# --- EXACT FEE CALIBRATION ---
GRID_TOTAL_INC_VAT = 61.13  
FORTUM_ADDONS_EX_VAT = 15.57 

def get_total_price_per_kwh(spot_price_ore_ex_vat):
    electricity_part_inc_vat = (spot_price_ore_ex_vat + FORTUM_ADDONS_EX_VAT) * 1.25
    return electricity_part_inc_vat + GRID_TOTAL_INC_VAT

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
        
        # NEON TRAFFIC LIGHT COLORS
        if total_ore < 100: color = "#00E676"   # Neon Green
        elif total_ore < 200: color = "#FFEA00" # Yellow
        else: color = "#FF1744"                 # Red

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

# --- MAIN APP LAYOUT ---
st.title("⚡ Power Monitor")

# 1. PROPERTY SELECTOR
selected_house_name = st.selectbox("Select Property", list(HOUSES.keys()))
current_house_config = HOUSES[selected_house_name]

# 2. FETCH DATA
df, last_updated = fetch_hourly_prices()
plug_status = get_tuya_status(current_house_config["plug_id"]) if current_house_config["has_smart_devices"] else None
heater_status = get_tuya_status(current_house_config["heater_id"]) if current_house_config["has_smart_devices"] else None

# Parse Smart Devices
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

# Current Price Logic
tz = pytz.timezone('Europe/Stockholm')
now = datetime.now(tz)
current_price_ore = 0.0
spot_now = 0.0

if df is not None:
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    if not current_row.empty:
        current_price_ore = current_row.iloc[0]['Total Price']
        spot_now = current_row.iloc[0]['Spot Price']

# --- SECTION 1: CALCULATORS & CONTROLS (THE FEATURE YOU MISSED) ---
# If Guest House, we show the SMART CONTROL first, but inside the same visual flow
if current_house_config["has_smart_devices"]:
    st.markdown("### 🔥 Climate Control")
    # Smart Status Box
    with st.container():
        c1, c2, c3 = st.columns(3)
        c1.metric("Indoors", f"{current_temp}°")
        c2.metric("Target", f"{target_temp}°")
        c3.metric("State", "ON" if heater_on else "OFF", f"{live_power_w:.0f} W")
        
        # Controls
        b1, b2, b3 = st.columns([1, 1, 2])
        with b1: 
            if st.button("❄️ -1°"):
                send_tuya_command(current_house_config["heater_id"], 'temp_set', target_temp - 1); st.rerun()
        with b2:
            if st.button("🔥 +1°"):
                send_tuya_command(current_house_config["heater_id"], 'temp_set', target_temp + 1); st.rerun()
        with b3:
            if st.button("⛔ STOP" if heater_on else "🚀 START", type="primary" if not heater_on else "secondary", use_container_width=True):
                send_tuya_command(current_house_config["heater_id"], 'switch', not heater_on); st.rerun()
    st.markdown("---")

# THE CALCULATOR EXPANDER (RESTORED EXACTLY)
with st.expander("🧮 Calculators & Bill Estimator", expanded=True):
    tab1, tab2 = st.tabs(["Appliance Cost", "Invoice Predictor"])
    
    with tab1:
        st.info(f"Analysis for: **{selected_house_name}**")
        
        # List of appliances
        apps = {
            "Heaters (Standard)": 1000,
            "Washing Machine": 2000,
            "Dryer": 2500,
            "Oven": 3000,
            "Sauna": 6000,
            "PC / TV": 200
        }
        
        # Dropdown
        app_choice = st.selectbox("Machine", list(apps.keys()))
        wattage = apps[app_choice]
        
        # Slider
        count = st.slider("Duration (Hours)", 1, 10, 1)
        
        # Calculation
        cost_now = (wattage / 1000.0) * count * (current_price_ore / 100.0)
        st.markdown(f"### Run NOW: :green[{cost_now:.2f} kr]")

    with tab2:
        st.write("Invoice estimation coming soon based on historic data.")

# --- SECTION 2: BIG PRICE DISPLAY ---
st.markdown("---")
# Use columns to get the "Spot | Grid" text next to the big number if desired, or below.
st.metric(label="Total Price", value=f"{current_price_ore:.2f} öre")
st.caption(f"Spot: {spot_now:.2f} | Grid: {GRID_TOTAL_INC_VAT:.2f}")

# --- SECTION 3: GRAPH (NEON GREEN) ---
st.subheader("Price Forecast (24h)")
if df is not None:
    # Active Bar Highlighting
    df['Opacity'] = df['Time'].apply(lambda x: 1.0 if x.hour == now.hour and x.date() == now.date() else 0.4)
    
    chart = alt.Chart(df[df['Time'] >= now - timedelta(hours=2)]).mark_bar(cornerRadius=4).encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M', title=None, domain=False, tickSize=0, labelColor='#888')),
        y=alt.Y('Total Price', axis=alt.Axis(title=None, domain=False, tickSize=0, labelColor='#888')),
        color=alt.Color('Color', scale=None),
        opacity=alt.Opacity('Opacity', legend=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=250).configure_view(strokeWidth=0).configure_axis(grid=False)
    
    st.altair_chart(chart, use_container_width=True)

# --- SECTION 4: SIGNAL GUIDE (RESTORED) ---
st.subheader("🎨 Signal Guide")
c1, c2, c3 = st.columns(3)
with c1: st.success("🟢 SAFE\n\nNight / Wknd")
with c2: st.warning("🟡 CAUTION\n\nDay 07-20")
with c3: st.error("🔴 EXPENSIVE\n\n> 2.00 SEK")

# Footer Sync
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()
