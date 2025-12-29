import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz
from tuya_connector import TuyaOpenAPI

# --- 1. PAGE CONFIG & MODERN STYLING ---
st.set_page_config(page_title="Power Monitor", page_icon="⚡", layout="centered")

# Custom CSS for "Modern Nordic" Look
st.markdown("""
    <style>
    /* Main Background */
    .stApp {
        background-color: #FAFCFF;
    }
    
    /* Card Styling for Metrics */
    div[data-testid="stMetric"] {
        background-color: #F0F8FF; /* AliceBlue */
        border: 1px solid #E1EAF5;
        border-radius: 12px;
        padding: 15px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    
    /* Headlines */
    h1, h2, h3 {
        color: #2c3e50;
        font-family: 'Helvetica Neue', sans-serif;
        font-weight: 600;
    }
    
    /* Buttons */
    div.stButton > button {
        border-radius: 8px;
        font-weight: 500;
        border: none;
        transition: all 0.3s;
    }
    
    /* Hide Default Header/Footer */
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

# --- 3. CONFIG & KEYS ---
REGION = "SE3"
TUYA_ACCESS_ID = "qdqkmyefdpqav3ckvnxm"      
TUYA_ACCESS_SECRET = "c1b019580ece45a2902c9d0df19a8e02"     
TUYA_ENDPOINT = "https://openapi.tuyaeu.com"
TUYA_PLUG_ID = "364820008cce4e2efeda"       
TUYA_HEATER_ID = "bf070e912f4a1df81dakvu"   

# --- EXACT FEE CALIBRATION (VERIFIED) ---
GRID_TOTAL_INC_VAT = 61.13  
FORTUM_ADDONS_EX_VAT = 15.57 

def get_total_price_per_kwh(spot_price_ore_ex_vat):
    electricity_part_inc_vat = (spot_price_ore_ex_vat + FORTUM_ADDONS_EX_VAT) * 1.25
    total_price = electricity_part_inc_vat + GRID_TOTAL_INC_VAT
    return total_price

# --- TUYA CONNECT ---
def get_tuya_status(device_id):
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
        
        # Modern Color Logic (Granular Blues/Teals)
        # Safe (Teal) -> Caution (Blue/Grey) -> Expensive (Muted Red)
        if total_ore < 100: color = "#4DD0E1"  # Cyan/Teal (Safe)
        elif total_ore < 200: color = "#90A4AE" # Blue Grey (Normal)
        else: color = "#E57373" # Soft Red (Expensive)

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
st.title("⚡ Guest House Energy")

# 1. Fetch Data
plug_status = get_tuya_status(TUYA_PLUG_ID)
heater_status = get_tuya_status(TUYA_HEATER_ID)
df, last_updated = fetch_hourly_prices()

# 2. Parse Devices
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

# 3. TOP SECTION: PRICE CARD
tz = pytz.timezone('Europe/Stockholm')
now = datetime.now(tz)
current_price_ore = 0.0

if df is not None:
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    if not current_row.empty:
        current_price_ore = current_row.iloc[0]['Total Price']
        
        # Hero Metric
        col_hero, col_btn = st.columns([2, 1])
        with col_hero:
            st.metric(
                label=f"Current Rate ({now.strftime('%H:%M')})", 
                value=f"{current_price_ore:.2f} öre",
                delta="Live Kvartspris",
                delta_color="off"
            )
        with col_btn:
             if st.button("🔄 Sync", type="secondary", use_container_width=True):
                 st.cache_data.clear()
                 st.rerun()

    # Modern Chart
    st.caption("Upcoming Prices (24h)")
    # Highlight Active Hour
    df['Opacity'] = df['Time'].apply(lambda x: 1.0 if x.hour == now.hour and x.date() == now.date() else 0.5)
    
    chart = alt.Chart(df[df['Time'] >= now - timedelta(hours=2)]).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M', title=None, grid=False)),
        y=alt.Y('Total Price', axis=alt.Axis(title=None, grid=False)),
        color=alt.Color('Color', scale=None),
        opacity=alt.Opacity('Opacity', legend=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=180).configure_view(strokeWidth=0)
    st.altair_chart(chart, use_container_width=True)

# 4. CONTROL SECTION
st.markdown("### 🌡️ Climate Control")

# Status Cards
c1, c2, c3 = st.columns(3)
with c1: st.metric("Indoors", f"{current_temp} °C")
with c2: st.metric("Target", f"{target_temp} °C")
with c3: 
    state_text = "Active" if heater_on else "Standby"
    st.metric("State", state_text)

# Cost Calculation
cost_per_hour_kr = (live_power_w / 1000.0) * (current_price_ore / 100.0)

# Main Action Area
with st.container():
    if heater_status:
        # Dynamic Feedback Line
        if live_power_w > 10:
            st.success(f"🔥 Heating is running at **{live_power_w:.0f} W** (~{cost_per_hour_kr:.2f} kr/h)")
        elif heater_on:
            st.info("💤 Heater is ON but idle (Target reached)")
        else:
            st.write("🌑 Heater is OFF")

        # Big Buttons
        b1, b2, b3 = st.columns([1, 1, 2])
        with b1:
            if st.button("❄️ -1°", use_container_width=True):
                send_tuya_command(TUYA_HEATER_ID, 'temp_set', target_temp - 1)
                st.rerun()
        with b2:
            if st.button("🔥 +1°", use_container_width=True):
                send_tuya_command(TUYA_HEATER_ID, 'temp_set', target_temp + 1)
                st.rerun()
        with b3:
            # Toggle Button Logic
            btn_label = "Stop Heating" if heater_on else "Start Heating"
            btn_type = "primary" if not heater_on else "secondary"
            if st.button(btn_label, type=btn_type, use_container_width=True):
                send_tuya_command(TUYA_HEATER_ID, 'switch', not heater_on)
                st.rerun()
    else:
        st.error("⚠️ Device Offline")
