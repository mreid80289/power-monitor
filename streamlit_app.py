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
    /* 1. THE MIDNIGHT GRADIENT BACKGROUND */
    .stApp {
        background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
        background-attachment: fixed;
    }
    
    /* 2. GLASSMORPHISM CARDS */
    div[data-testid="stMetric"], div[data-testid="stExpander"], div.stContainer {
        background: rgba(255, 255, 255, 0.05); /* 5% White Transparency */
        backdrop-filter: blur(10px);           /* Frosted Glass Effect */
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 20px;                   /* Very Rounded Corners */
        padding: 20px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        color: white;
    }
    
    /* 3. TYPOGRAPHY & COLORS */
    h1, h2, h3, p, div, span, label {
        color: #ffffff !important;
        font-family: 'Inter', 'Segoe UI', sans-serif;
        font-weight: 300;
    }
    h1 { font-weight: 700; text-shadow: 0 0 10px rgba(0,255,255,0.5); }
    
    /* 4. BUTTONS (PILL SHAPE) */
    div.stButton > button {
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%);
        color: white;
        border: none;
        border-radius: 30px; /* Pill Shape */
        height: 3.5em;
        font-weight: 600;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(75, 108, 183, 0.6);
    }
    /* Secondary/Stop Button Styling */
    div.stButton > button[kind="secondary"] {
        background: linear-gradient(90deg, #eb3349 0%, #f45c43 100%);
    }

    /* 5. METRIC VALUES (BIG NUMBERS) */
    div[data-testid="stMetricValue"] {
        font-size: 2rem !important;
        background: -webkit-linear-gradient(#00c6ff, #0072ff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
    }
    
    /* 6. HIDE STREAMLIT CHROME */
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
    st.text_input("🔒 Login", type="password", on_change=password_entered, key="password")
    return False

if not check_password(): st.stop()

# --- 3. SETUP & KEYS ---
REGION = "SE3"
TUYA_ACCESS_ID = "qdqkmyefdpqav3ckvnxm"      
TUYA_ACCESS_SECRET = "c1b019580ece45a2902c9d0df19a8e02"     
TUYA_ENDPOINT = "https://openapi.tuyaeu.com"

HOUSES = {
    "Main House": {"has_smart_devices": False, "plug_id": "", "heater_id": ""},
    "Guest House": {"has_smart_devices": True, "plug_id": "364820008cce4e2efeda", "heater_id": "bf070e912f4a1df81dakvu"}
}

GRID_TOTAL_INC_VAT = 61.13  
FORTUM_ADDONS_EX_VAT = 15.57 

def get_total_price_per_kwh(spot_price_ore_ex_vat):
    electricity_part_inc_vat = (spot_price_ore_ex_vat + FORTUM_ADDONS_EX_VAT) * 1.25
    return electricity_part_inc_vat + GRID_TOTAL_INC_VAT

# --- TUYA FUNCTIONS ---
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
        
        # GRADIENT COLORS FOR CHART (Matches the Blue/Cyan theme)
        # We use opacity or slight color shifts for high prices instead of stark red/green
        if total_ore < 100: color = "#00c6ff"   # Cyan
        elif total_ore < 200: color = "#0072ff" # Blue
        else: color = "#f45c43"                 # Red/Orange

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
st.title("Smart Home")

# 1. HOUSE SELECTOR
selected_house_name = st.selectbox("Select Property", list(HOUSES.keys()))
current_house_config = HOUSES[selected_house_name]

# 2. DATA FETCH
df, last_updated = fetch_hourly_prices()
plug_status = get_tuya_status(current_house_config["plug_id"]) if current_house_config["has_smart_devices"] else None
heater_status = get_tuya_status(current_house_config["heater_id"]) if current_house_config["has_smart_devices"] else None

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

tz = pytz.timezone('Europe/Stockholm')
now = datetime.now(tz)
current_price_ore = 0.0
if df is not None:
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    if not current_row.empty:
        current_price_ore = current_row.iloc[0]['Total Price']

# --- SECTION 1: HEADER METRICS (Glass Cards) ---
c1, c2 = st.columns(2)
with c1:
    st.metric("Live Price", f"{current_price_ore:.0f} öre", "Exact Rate")
with c2:
    if current_house_config["has_smart_devices"]:
        cost_now = (live_power_w / 1000.0) * (current_price_ore / 100.0)
        st.metric("Consumption", f"{live_power_w:.0f} W", f"{cost_now:.2f} kr/h")
    else:
        st.metric("Consumption", "--", "No Sensor")

# --- SECTION 2: GRAPH (Modern Gradient) ---
st.write("### Price Trend")
if df is not None:
    df['Opacity'] = df['Time'].apply(lambda x: 1.0 if x.hour == now.hour and x.date() == now.date() else 0.4)
    chart = alt.Chart(df[df['Time'] >= now - timedelta(hours=2)]).mark_bar(cornerRadius=5).encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M', title=None, domain=False, tickSize=0, labelColor='white')),
        y=alt.Y('Total Price', axis=alt.Axis(title=None, domain=False, tickSize=0, labelColor='white')),
        color=alt.Color('Color', scale=None),
        opacity=alt.Opacity('Opacity', legend=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=220, background='transparent').configure_view(strokeWidth=0).configure_axis(grid=False)
    st.altair_chart(chart, use_container_width=True)

# --- SECTION 3: CONTROL PANEL (Smart Home UI) ---
if current_house_config["has_smart_devices"]:
    st.write("### Climate Control")
    with st.container():
        # Top Row: Status
        c_temp, c_targ, c_stat = st.columns(3)
        c_temp.metric("Indoor", f"{current_temp}°")
        c_targ.metric("Target", f"{target_temp}°")
        c_stat.metric("State", "ON" if heater_on else "OFF")
        
        # Bottom Row: Buttons (Pill Shaped)
        b1, b2, b3 = st.columns([1, 1, 1.5])
        with b1: 
            if st.button("Temp -1°"):
                send_tuya_command(current_house_config["heater_id"], 'temp_set', target_temp - 1); st.rerun()
        with b2:
            if st.button("Temp +1°"):
                send_tuya_command(current_house_config["heater_id"], 'temp_set', target_temp + 1); st.rerun()
        with b3:
            # Styled Stop/Start button
            btn_txt = "STOP" if heater_on else "START"
            if st.button(btn_txt, type="primary" if not heater_on else "secondary"):
                send_tuya_command(current_house_config["heater_id"], 'switch', not heater_on); st.rerun()

# --- SECTION 4: CALCULATOR TABS ---
st.write("### Cost Analysis")
tab1, tab2 = st.tabs(["Calculator", "Estimates"])

with tab1:
    apps = {
        "Heaters (Standard 1000W)": {"watts": 1000, "type": "quantity"},
        "Lights (Standard 60W)":    {"watts": 60,   "type": "quantity"},
        "Washing Machine":          {"watts": 2000, "type": "duration"},
        "Dryer":                    {"watts": 2500, "type": "duration"},
        "Sauna":                    {"watts": 6000, "type": "duration"},
    }
    
    app_choice = st.selectbox("Select Device", list(apps.keys()))
    selected_data = apps[app_choice]
    
    if selected_data["type"] == "quantity":
        qty = st.slider("Quantity", 1, 20, 1)
        cost_calc = (selected_data["watts"] * qty / 1000.0) * (current_price_ore / 100.0)
        st.write(f"### Hourly Cost: {cost_calc:.2f} kr")
    else:
        hrs = st.slider("Duration (Hours)", 1, 10, 1)
        cost_calc = (selected_data["watts"] / 1000.0) * hrs * (current_price_ore / 100.0)
        st.write(f"### Cycle Cost: {cost_calc:.2f} kr")

with tab2:
    st.info("Historic bill estimation module loading...")

# Footer
st.markdown("---")
if st.button("🔄 Refresh System"):
    st.cache_data.clear()
    st.rerun()
