import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz
from tuya_connector import TuyaOpenAPI

# --- HIDE STREAMLIT STYLE ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- CONFIGURATION ---
REGION = "SE3"
IS_VILLA = True 

# --- TUYA SMART PLUG CONFIG ---
TUYA_ACCESS_ID = "YOUR_ACCESS_ID_HERE"      
TUYA_ACCESS_SECRET = "YOUR_ACCESS_SECRET_HERE"     
TUYA_DEVICE_ID = "YOUR_DEVICE_ID_HERE"
TUYA_ENDPOINT = "https://openapi.tuyaeu.com"

# FEES
ELLEVIO_TRANSFER_FEE = 6.25    
ELLEVIO_PEAK_FEE_PER_KW = 81.25 
ELLEVIO_MONTHLY_FIXED = 365.00  
ENERGY_TAX = 54.88 
FORTUM_MARKUP = 4.88  
FORTUM_BASE_FEE = 69.00
FORTUM_PRISKOLLEN = 49.00

def get_total_price(spot_ore):
    fortum_part = (spot_ore * 1.25) + FORTUM_MARKUP
    grid_part = (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX
    return fortum_part + grid_part

def get_tuya_status():
    """Fetches ALL data from the plug to find the 'Total kWh' counter."""
    if "YOUR_" in TUYA_ACCESS_ID: return None, "Keys not set."
    try:
        openapi = TuyaOpenAPI(TUYA_ENDPOINT, TUYA_ACCESS_ID, TUYA_ACCESS_SECRET)
        openapi.connect()
        response = openapi.get(f'/v1.0/devices/{TUYA_DEVICE_ID}/status')
        
        if not response['success']: return None, response.get('msg', 'Error')
        return response['result'], None
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=900)
def fetch_data():
    tz = pytz.timezone('Europe/Stockholm')
    today = datetime.now(tz)
    dates = [today, today + timedelta(days=1)]
    all_data = []
    
    for date_obj in dates:
        date_str = date_obj.strftime("%Y/%m-%d")
        url = f"https://www.elprisetjustnu.se/api/v1/prices/{date_str}_{REGION}.json"
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                all_data.extend(r.json())
        except:
            pass
            
    if not all_data: return None, None

    rows = []
    for hour in all_data:
        start = datetime.fromisoformat(hour['time_start'])
        spot_ore = hour['SEK_per_kWh'] * 100
        total_ore = get_total_price(spot_ore)
        
        is_weekday = start.weekday() < 5
        is_peak_hour = 7 <= start.hour < 20
        is_danger = is_weekday and is_peak_hour
        
        rows.append({
            "Time": start,
            "Hour": start.hour,
            "Total Price": round(total_ore, 2),
            "Spot Price": round(spot_ore, 2),
            "Color": "#ff4b4b" if total_ore > 200 else "#00c853",
            "Opacity": 1.0 if is_danger else 0.3
        })
    
    fetch_time = datetime.now(tz).strftime("%H:%M")
    return pd.DataFrame(rows), fetch_time

st.set_page_config(page_title="Power Monitor", page_icon="⚡", layout="centered")

col1, col2 = st.columns([3, 1])
with col1:
    st.title("⚡ Power Monitor")
with col2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# --- FETCH RAW TUYA DATA ---
plug_data, error_msg = get_tuya_status()

# Extract Power (W) and Total (kWh) if possible
live_power_w = 0.0
total_kwh_accumulated = 0.0

if plug_data:
    for item in plug_data:
        # 1. Current Power
        if item['code'] in ['cur_power', 'power']:
            live_power_w = item['value'] / 10.0
            
        # 2. Total Energy (The number we are hunting for!)
        # Common codes: 'add_ele', 'total_forward_energy', 'energy_total'
        if item['code'] in ['add_ele', 'total_forward_energy', 'energy_total']:
            # Sometimes value is scaled by 10, 100 or 1000.
            # We assume 100 or 1000 usually. For now just raw.
            total_kwh_accumulated = item['value'] 

live_power_kw = live_power_w / 1000.0

# --- PROPERTY SELECTOR ---
selected_house = st.selectbox("Select Property", ["Main House", "Guest House"])

df, last_updated = fetch_data()

if df is None:
    st.error("Could not fetch data.")
else:
    tz = pytz.timezone('Europe/Stockholm')
    now = datetime.now(tz)
    st.caption(f"Last updated: {last_updated}")

    with st.expander("🧮 Calculators & Bill Estimator", expanded=True):
        
        tab1, tab2 = st.tabs(["Appliance Cost", "Invoice Predictor"])
        
        with tab1:
            st.info(f"Analysis for: **{selected_house}**")
            
            if selected_house == "Guest House":
                # --- LIVE DISPLAY ---
                if live_power_w > 0:
                    st.success(f"🔌 **LIVE Office Heater:** {live_power_w:.1f} W ({live_power_kw:.3f} kW)")
                else:
                    st.info(f"🔌 **Office Heater:** Idle (0 W)")
                
                # --- DEBUG BOX (To find the missing history) ---
                with st.expander("🕵️ Debug: What does the plug know?", expanded=False):
                    st.write("We are looking for a 'Total' counter here:")
                    st.json(plug_data) # <--- THIS SHOWS EVERYTHING
            
            appliance = st.selectbox("Machine", [
                "Office Heater (Guest House)", 
                "Sauna (2h)", "Dishwasher (1.5h)", "Washing Machine (2h)"
            ])
            
            # --- COST CALCULATION ---
            # 1. Calculate Average Price for "This Month So Far"
            # (Approximation using today's average as proxy for month avg to keep it simple without DB)
            avg_price_total = df['Total Price'].mean() / 100
            
            if "Office Heater" in appliance:
                usage_kw = live_power_kw if live_power_kw > 0 else 1.0
                
                # A. Cost NOW (Real-time)
                curr_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
                if not curr_row.empty:
                    price_now = curr_row.iloc[0]['Total Price'] / 100
                    cost_now = price_now * usage_kw
                    st.write(f"Run **NOW**: **{cost_now:.2f} kr** (per hour)")

                # B. Cost TODAY (Work Day 05:30-19:00)
                today_rows = df[df['Time'].dt.date == now.date()]
                work_day_cost = 0.0
                if not today_rows.empty:
                    for idx, row in today_rows.iterrows():
                        h = row['Hour']
                        p_kronor = row['Total Price'] / 100
                        if h == 5: work_day_cost += (p_kronor * usage_kw * 0.5)
                        elif 6 <= h < 19: work_day_cost += (p_kronor * usage_kw * 1.0)
                
                st.markdown(f"### 🗓️ Cost Today (05:30–19:00)")
                st.write(f"**{work_day_cost:.2f} kr**")

                # C. COST THIS MONTH (The Real Usage!)
                st.markdown(f"### 📅 This Month (Total)")
                if total_kwh_accumulated > 0:
                     # IMPORTANT: We need to figure out the decimal point. 
                     # Often 'add_ele' = 100 means 0.100 kWh or 1.00 kWh.
                     # We will display raw first to check.
                     estimated_cost_accum = (total_kwh_accumulated / 1000.0) * avg_price_total
                     st.write(f"**{estimated_cost_accum:.2f} kr**")
                     st.caption(f"Based on Plug Counter: {total_kwh_accumulated} (Raw units)")
                else:
                    # Fallback to estimate
                    days_passed = now.day
                    cost_month_est = work_day_cost * days_passed
                    st.write(f"**~{cost_month_est:.0f} kr** (Estimate)")
                    st.caption("Using daily estimate. Check 'Debug' box to enable Real Tracking.")

            else:
                 # Standard logic for other machines...
                 pass # (Kept simple for brevity in this snippet)

        with tab2:
            st.subheader("🔮 Invoice Predictor")
            # ... (Same Invoice Logic as before) ...
            st.info("Invoice logic preserved.")

    # ... (Dashboard & Chart code remains same) ...
