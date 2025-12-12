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
TUYA_ACCESS_ID = "qdqkmyefdpqav3ckvnxm"      
TUYA_ACCESS_SECRET = "c1b019580ece45a2902c9d0df19a8e02"     
TUYA_DEVICE_ID = "364820008cce4e2efeda"
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

def get_tuya_power():
    if "YOUR_" in TUYA_ACCESS_ID: return 0.0, "Keys not set."
    try:
        openapi = TuyaOpenAPI(TUYA_ENDPOINT, TUYA_ACCESS_ID, TUYA_ACCESS_SECRET)
        openapi.connect()
        response = openapi.get(f'/v1.0/devices/{TUYA_DEVICE_ID}/status')
        
        if not response['success']: return 0.0, response.get('msg', 'Error')
        
        for item in response['result']:
            if item['code'] in ['cur_power', 'power']:
                return (item['value'] / 10.0), None 
        return 0.0, "No power reading"
    except Exception as e:
        return 0.0, str(e)

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

# --- FETCH LIVE DATA ---
live_plug_power_w, error_msg = get_tuya_power()
live_plug_power_kw = live_plug_power_w / 1000.0

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
            
            # --- CONDITIONAL LIVE DISPLAY (GUEST HOUSE ONLY) ---
            if selected_house == "Guest House":
                if live_plug_power_w > 0:
                    st.success(f"🔌 **LIVE Office Heater:** {live_plug_power_w:.1f} W ({live_plug_power_kw:.3f} kW)")
                elif error_msg:
                    st.error(f"⚠️ Heater Connection Failed: {error_msg}")
                else:
                    st.info(f"🔌 **Office Heater:** Connected but Idle (0 W)")
            
            # --- APPLIANCE LIST ---
            appliance = st.selectbox("Machine", [
                "Office Heater (Guest House)", # Renamed
                "Sauna (2h)", 
                "Dishwasher (1.5h)", 
                "Washing Machine (2h)"
            ])
            
            # --- CALCULATIONS ---
            if "Office Heater" in appliance:
                # Use live data if available, otherwise default to 1.0 kW
                usage_kw = live_plug_power_kw if live_plug_power_kw > 0 else 1.0
                duration = 24.0 # For the 24h calc
                label = "24 hours"
            elif "Sauna" in appliance: usage_kw = 6.0; duration=2; label="total"
            elif "Dishwasher" in appliance: usage_kw = 1.2; duration=1.5; label="total"
            elif "Washing" in appliance: usage_kw = 1.5; duration=2; label="total"
            
            # Current Hour Cost
            curr_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
            
            if not curr_row.empty:
                # 1. Cost NOW (Instant)
                price_now = curr_row.iloc[0]['Total Price'] / 100
                cost_now = price_now * usage_kw * (1.0 if "Heater" in appliance else duration)
                
                # 2. Cost 24H (For Heater)
                if "Office Heater" in appliance:
                    # Calculate average price for next 24h
                    future_24h = df[df['Time'] >= now].head(24)
                    if not future_24h.empty:
                        avg_price_24h = future_24h['Total Price'].mean() / 100
                        cost_24h = avg_price_24h * usage_kw * 24.0
                        
                        st.write(f"Run **NOW**: **{cost_now:.2f} kr** (per hour)")
                        st.write(f"Run **24 Hours**: **{cost_24h:.2f} kr** (Continuous)")
                else:
                    st.write(f"Run **NOW**: **{cost_now:.2f} kr** ({label})")

        with tab2:
            st.subheader("🔮 Invoice Predictor")
            has_priskollen = st.checkbox("Include 'Priskollen' Fee (49kr)?", value=True)
            fortum_fixed_calc = FORTUM_BASE_FEE + (FORTUM_PRISKOLLEN if has_priskollen else 0)
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("### 🏠 Main")
                main_kwh = st.number_input("kWh", value=1069)
                main_peak = st.number_input("Peak (kW)", value=6.9)
                m_total = (main_kwh * 1.00) + fortum_fixed_calc + \
                          (main_kwh * ((ELLEVIO_TRANSFER_FEE*1.25)+ENERGY_TAX)/100) + \
                          (ELLEVIO_MONTHLY_FIXED + (main_peak * ELLEVIO_PEAK_FEE_PER_KW))
                st.caption(f"Est: {m_total:.0f} kr")

            with col_b:
                st.markdown("### 🏚️ Guest")
                guest_kwh = st.number_input("Guest kWh", value=517)
                
                # Auto-fill peak if live data is high
                default_guest_peak = max(3.6, live_plug_power_kw)
                guest_peak = st.number_input("Peak (kW)", value=default_guest_peak)
                
                g_total = (guest_kwh * 1.00) + fortum_fixed_calc + \
                          (guest_kwh * ((ELLEVIO_TRANSFER_FEE*1.25)+ENERGY_TAX)/100) + \
                          (ELLEVIO_MONTHLY_FIXED + (guest_peak * ELLEVIO_PEAK_FEE_PER_KW))
                st.caption(f"Est: {g_total:.0f} kr")
            
            st.divider()
            st.metric("TOTAL FOR BOTH", f"{(m_total + g_total):.0f} kr")

    # --- MAIN DASHBOARD ---
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    if not current_row.empty:
        price = current_row.iloc[0]['Total Price']
        spot = current_row.iloc[0]['Spot Price']
        grid = (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Price", f"{price:.2f} öre", delta_color="inverse", 
                    delta="- Low" if price < 150 else "+ High")
        with col2:
             st.caption(f"Spot: {spot} | Grid: {grid:.1f}")

    st.subheader("Price Forecast (24h)")
    
    start_view = now - timedelta(hours=2)
    chart_data = df[df['Time'] >= start_view]
    
    bars = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M')),
        y=alt.Y('Total Price'),
        color=alt.Color('Color', scale=None),
        opacity=alt.Opacity('Opacity', scale=None),
        tooltip=['Time', 'Total Price']
    )
    now_line_data = pd.DataFrame({'Time': [now]})
    rule = alt.Chart(now_line_data).mark_rule(color='orange', size=2).encode(x='Time')
    
    st.altair_chart((bars + rule).properties(height=300), use_container_width=True)

    st.markdown("### 🎨 Signal Guide")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.success("🟢 **SAFE**")
        st.caption("Night / Wknd")
    with c2:
        st.warning("🟢 **CAUTION**")
        st.caption("Day 07-20")
    with c3:
        st.error("🔴 **EXPENSIVE**")
        st.caption("> 2.00 SEK")

