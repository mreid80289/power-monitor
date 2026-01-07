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
    .stApp { background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%); background-attachment: fixed; }
    div[data-testid="stMetric"], div[data-testid="stExpander"], div.stContainer {
        background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 20px; padding: 20px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37); color: white;
    }
    h1, h2, h3, p, div, span, label { color: #ffffff !important; font-family: 'Inter', 'Segoe UI', sans-serif; font-weight: 300; }
    h1 { font-weight: 700; text-shadow: 0 0 10px rgba(0,255,255,0.5); }
    div.stButton > button {
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%); color: white;
        border: none; border-radius: 30px; height: 3.5em; font-weight: 600;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2); transition: all 0.3s ease;
    }
    div.stButton > button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(75, 108, 183, 0.6); }
    div.stButton > button[kind="secondary"] { background: linear-gradient(90deg, #eb3349 0%, #f45c43 100%); }
    div[data-testid="stMetricValue"] {
        font-size: 2rem !important; background: -webkit-linear-gradient(#00c6ff, #0072ff);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800;
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

# --- 3. SETUP & KEYS ---
REGION = "SE3"
TUYA_ACCESS_ID = "qdqkmyefdpqav3ckvnxm"      
TUYA_ACCESS_SECRET = "c1b019580ece45a2902c9d0df19a8e02"     
TUYA_ENDPOINT = "https://openapi.tuyaeu.com"

HOUSES = {
    "Main House": {"has_smart_devices": False, "plug_id": "", "heater_id": ""},
    "Guest House": {"has_smart_devices": True, "plug_id": "364820008cce4e2efeda", "heater_id": "bf070e912f4a1df81dakvu"}
}

# --- 4. PRICING LOGIC (2026 UPDATED) ---
# Ellevio (SE3 2026): ~7.00 öre/kWh transfer + ~46.00 öre/kWh energy tax (inc VAT)
# Fortum Tarkka (2026): Spot + 0.59 öre/kWh fee (ex VAT)
ENERGY_TAX_INC_VAT = 46.00 
ELLEVIO_TRANSFER_INC_VAT = 8.75 # 7 öre * 1.25
FORTUM_FEE_INC_VAT = 0.74 # 0.59 öre * 1.25

def get_total_price_per_kwh(spot_price_ore_ex_vat):
    # Calculate electricity part (Spot + Fortum Fee) + 25% VAT
    elec_inc_vat = (spot_price_ore_ex_vat * 1.25) + FORTUM_FEE_INC_VAT
    # Add Grid costs (Tax + Transfer)
    total = elec_inc_vat + ENERGY_TAX_INC_VAT + ELLEVIO_TRANSFER_INC_VAT
    return total

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
        
        if total_ore < 150: color = "#00c6ff"   # Low/Mid
        elif total_ore < 250: color = "#0072ff" # Normal
        else: color = "#f45c43"                 # High

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

selected_house_name = st.selectbox("Select Property", list(HOUSES.keys()))
current_house_config = HOUSES[selected_house_name]

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

# --- SECTION 1: HEADER METRICS ---
c1, c2 = st.columns(2)
with c1:
    st.metric("Total Price", f"{current_price_ore:.2f} öre", "All inclusive")
with c2:
    if current_house_config["has_smart_devices"]:
        # ACTUAL COST CALCULATION: (Watts / 1000) * (Price / 100)
        cost_now_kr = (live_power_w / 1000.0) * (current_price_ore / 100.0)
        st.metric("Live Consumption", f"{live_power_w:.1f} W", f"{cost_now_kr:.2f} kr/h")
    else:
        st.metric("Consumption", "--", "No Sensor")

# --- SECTION 2: GRAPH ---
st.write("### Price Trend (All inclusive)")
if df is not None:
    df['Opacity'] = df['Time'].apply(lambda x: 1.0 if x.hour == now.hour and x.date() == now.date() else 0.4)
    chart = alt.Chart(df[df['Time'] >= now - timedelta(hours=2)]).mark_bar(cornerRadius=5).encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M', title=None, labelColor='white')),
        y=alt.Y('Total Price', axis=alt.Axis(title=None, labelColor='white')),
        color=alt.Color('Color', scale=None),
        opacity=alt.Opacity('Opacity', legend=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=220).configure_view(strokeWidth=0).configure_axis(grid=False)
    st.altair_chart(chart, use_container_width=True)

# --- SECTION 3: CONTROL PANEL ---
if current_house_config["has_smart_devices"]:
    st.write("### Climate Control")
    with st.container():
        c_temp, c_targ, c_stat = st.columns(3)
        c_temp.metric("Indoor", f"{current_temp}°")
        c_targ.metric("Target", f"{target_temp}°")
        c_stat.metric("State", "ON" if heater_on else "OFF")
        
        b1, b2, b3 = st.columns([1, 1, 1.5])
        with b1: 
            if st.button("Temp -1°"):
                send_tuya_command(current_house_config["heater_id"], 'temp_set', target_temp - 1); st.rerun()
        with b2:
            if st.button("Temp +1°"):
                send_tuya_command(current_house_config["heater_id"], 'temp_set', target_temp + 1); st.rerun()
        with b3:
            btn_txt = "STOP" if heater_on else "START"
            if st.button(btn_txt, type="primary" if not heater_on else "secondary"):
                send_tuya_command(current_house_config["heater_id"], 'switch', not heater_on); st.rerun()

# Footer
st.markdown("---")
if st.button("🔄 Refresh System"):
    st.cache_data.clear()
    st.rerun()
