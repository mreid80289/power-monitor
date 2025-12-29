import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz
from tuya_connector import TuyaOpenAPI

# --- 1. PAGE CONFIG ---
st.set_page_config(page_title="Power Monitor", page_icon="⚡", layout="centered")

# --- 2. HIDE STREAMLIT STYLE ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- 3. PASSWORD PROTECTION ---
def check_password():
    if st.session_state.get("password_correct", False): return True
    
    def password_entered():
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    st.text_input("🔒 Enter Password", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state: st.error("😕 Password incorrect")
    return False

if not check_password(): st.stop()

# --- 4. APP CONFIGURATION ---
REGION = "SE3"

# --- TUYA KEYS (Verified) ---
TUYA_ACCESS_ID = "qdqkmyefdpqav3ckvnxm"      
TUYA_ACCESS_SECRET = "c1b019580ece45a2902c9d0df19a8e02"     
TUYA_ENDPOINT = "https://openapi.tuyaeu.com"
TUYA_PLUG_ID = "364820008cce4e2efeda"       # Smart Plug
TUYA_HEATER_ID = "bf070e912f4a1df81dakvu"   # Office Heater

# --- EXACT FEE CALIBRATION (NOV/DEC BILLS) ---
# 1. Ellevio Grid (Inc VAT): Transfer (6.25) + Tax (54.88)
GRID_TOTAL_INC_VAT = 61.13  

# 2. Fortum Add-ons (Ex VAT): 
# Markup (2.00) + Certs (1.90) + Variable (11.67)
FORTUM_ADDONS_EX_VAT = 15.57 

def get_total_price_per_kwh(spot_price_ore_ex_vat):
    """
    Calculates the EXACT price you pay for 1 kWh at a specific hour.
    Formula: ((Spot + FortumFees) * 1.25 VAT) + GridFeesIncVAT
    """
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
@st.cache_data(ttl=900) # Update cache every 15 mins
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
        spot_ore = hour['SEK_per_kWh'] * 100 # API is in SEK, convert to öre
        
        # KEY CALCULATION
        total_ore = get_total_price_per_kwh(spot_ore)
        
        rows.append({
            "Time": start, 
            "Hour": start.hour,
            "Total Price": round(total_ore, 2), 
            "Spot Price": round(spot_ore, 2),
            "Color": "#d32f2f" if total_ore > 200 else ("#fbc02d" if total_ore > 100 else "#388e3c")
        })
    
    df = pd.DataFrame(rows)
    df.drop_duplicates(subset=['Time'], inplace=True)
    return df, datetime.now(tz)

# --- MAIN APP UI ---
col1, col2 = st.columns([3, 1])
with col1: st.title("⚡ Power Monitor")
with col2: 
    if st.button("🔄 Refresh"): st.cache_data.clear(); st.rerun()

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

# 3. Determine CURRENT Price
tz = pytz.timezone('Europe/Stockholm')
now = datetime.now(tz)
current_price_ore = 0.0

if df is not None:
    # Filter for THIS specific hour
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    if not current_row.empty:
        current_price_ore = current_row.iloc[0]['Total Price']
        spot_now = current_row.iloc[0]['Spot Price']
        
        # Display BIG Price
        st.metric(
            label=f"Current Price ({now.strftime('%H:%M')})", 
            value=f"{current_price_ore:.2f} öre/kWh",
            delta=f"Spot: {spot_now:.1f} öre",
            delta_color="off"
        )
    
    # Chart
    st.subheader("Price Forecast (24h)")
    # Highlight current hour in chart
    df['Active'] = df['Time'].apply(lambda x: 1.0 if x.hour == now.hour and x.date() == now.date() else 0.4)
    
    chart = alt.Chart(df[df['Time'] >= now - timedelta(hours=2)]).mark_bar().encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M')),
        y=alt.Y('Total Price'),
        color=alt.Color('Color', scale=None),
        opacity=alt.Opacity('Active', legend=None),
        tooltip=['Time', 'Total Price', 'Spot Price']
    ).properties(height=250)
    st.altair_chart(chart, use_container_width=True)

# 4. Heater Control & Cost
st.markdown("---")
st.subheader("🔥 Guest House Control")

c1, c2, c3 = st.columns(3)
c1.metric("Room Temp", f"{current_temp} °C")
c2.metric("Target", f"{target_temp} °C")
c3.metric("Heater State", "ON" if heater_on else "OFF")

# Calculate "Run Rate" (Cost per hour RIGHT NOW)
cost_per_hour_kr = (live_power_w / 1000.0) * (current_price_ore / 100.0)

if heater_status:
    if live_power_w > 10:
        st.success(f"⚡ **Heating Active:** Consuming {live_power_w:.0f} W")
        st.write(f"💸 **Cost Right Now:** {cost_per_hour_kr:.2f} kr / hour")
    else:
        st.info("💤 Heater is Idle (0 W)")

    # Controls
    cc1, cc2, cc3 = st.columns([1,1,2])
    with cc1:
        if st.button("❄️ -1°"):
            send_tuya_command(TUYA_HEATER_ID, 'temp_set', target_temp - 1)
            st.rerun()
    with cc2:
        if st.button("🔥 +1°"):
            send_tuya_command(TUYA_HEATER_ID, 'temp_set', target_temp + 1)
            st.rerun()
    with cc3:
        if st.button(f"Turn {'OFF' if heater_on else 'ON'}", type="primary" if not heater_on else "secondary", use_container_width=True):
            send_tuya_command(TUYA_HEATER_ID, 'switch', not heater_on)
            st.rerun()
else:
    st.error("⚠️ Heater Offline")

# 5. Simple Estimator (Footer)
st.markdown("---")
with st.expander("📊 Quick Estimates"):
    st.caption("Based on your REAL live 'Kvartspris' contract.")
    st.write(f"**Grid Fees (Fixed per kWh):** {GRID_TOTAL_INC_VAT} öre")
    st.write(f"**Fortum Add-ons (Ex VAT):** {FORTUM_ADDONS_EX_VAT} öre")
    st.info("Prices update automatically every hour.")
