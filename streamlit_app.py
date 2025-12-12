import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz
from tuya_connector import TuyaOpenAPI

# --- 1. PAGE CONFIG MUST BE FIRST ---
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
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't store the password
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input(
        "🔒 Enter Password", type="password", on_change=password_entered, key="password"
    )
    
    if "password_correct" in st.session_state:
        st.error("😕 Password incorrect")
        
    return False

if not check_password():
    st.stop()

# --- 4. YOUR APP STARTS HERE ---

# --- CONFIGURATION (UPDATED FROM DEC 2025 BILLS) ---
REGION = "SE3"
IS_VILLA = True 

# --- TUYA DEVICES CONFIG ---
TUYA_ACCESS_ID = "qdqkmyefdpqav3ckvnxm"      
TUYA_ACCESS_SECRET = "c1b019580ece45a2902c9d0df19a8e02"     
TUYA_ENDPOINT = "https://openapi.tuyaeu.com"

# 1. SMART PLUG (Power)
TUYA_PLUG_ID = "364820008cce4e2efeda"

# 2. OFFICE HEATER (Temp Control)
TUYA_HEATER_ID = "bf070e912f4a1df81dakvu" 

# PLUG SETTINGS
PLUG_SCALING_FACTOR = 10.0 

# --- FEES & TAXES (CALIBRATED) ---
# Ellevio Transfer: 6.25 inkl moms -> 5.00 exkl moms
ELLEVIO_TRANSFER_FEE_EX_VAT = 5.00    
# Energy Tax is usually taxed, bill says 54.88 inkl moms
ENERGY_TAX_INC_VAT = 54.88 

# Fortum Markup: 2.00 + 1.90 (Cert) + 11.67 (Var) = 15.57 exkl moms -> 19.46 inkl moms
FORTUM_MARKUP_INC_VAT = 19.46  

# Monthly Fixed Costs (Inkl Moms)
ELLEVIO_MONTHLY_FIXED = 365.00  
ELLEVIO_PEAK_FEE_PER_KW = 81.25 
FORTUM_BASE_FEE = 69.00
FORTUM_PRISKOLLEN = 49.00

def get_total_price(spot_ore):
    # Spot is ex VAT. We add 25% VAT.
    # Fortum Markup is already Inc VAT.
    fortum_part = (spot_ore * 1.25) + FORTUM_MARKUP_INC_VAT
    
    # Grid Transfer is Ex VAT in config, so we add 25%.
    # Energy Tax is Inc VAT in config.
    grid_part = (ELLEVIO_TRANSFER_FEE_EX_VAT * 1.25) + ENERGY_TAX_INC_VAT
    
    return fortum_part + grid_part

def get_tuya_status(device_id):
    if "YOUR_" in TUYA_ACCESS_ID: return None, "Keys not set."
    try:
        openapi = TuyaOpenAPI(TUYA_ENDPOINT, TUYA_ACCESS_ID, TUYA_ACCESS_SECRET)
        openapi.connect()
        response = openapi.get(f'/v1.0/devices/{device_id}/status')
        if not response['success']: return None, response.get('msg', 'Error')
        return response['result'], None
    except Exception as e:
        return None, str(e)

def send_tuya_command(device_id, code, value):
    try:
        openapi = TuyaOpenAPI(TUYA_ENDPOINT, TUYA_ACCESS_ID, TUYA_ACCESS_SECRET)
        openapi.connect()
        commands = {'commands': [{'code': code, 'value': value}]}
        openapi.post(f'/v1.0/devices/{device_id}/commands', commands)
        return True
    except:
        return False

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
        rows.append({
            "Time": start, "Hour": start.hour,
            "Total Price": round(total_ore, 2), "Spot Price": round(spot_ore, 2),
            "Color": "#ff4b4b" if total_ore > 200 else "#00c853",
            "Opacity": 1.0
        })
    
    df = pd.DataFrame(rows)
    df.drop_duplicates(subset=['Time'], inplace=True)
    fetch_time = datetime.now(tz).strftime("%H:%M")
    return df, fetch_time

col1, col2 = st.columns([3, 1])
with col1: st.title("⚡ Power Monitor")
with col2: 
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# --- FETCH DATA ---
plug_data, plug_err = get_tuya_status(TUYA_PLUG_ID)
live_power_w = 0.0; total_kwh_accumulated = 0.0
if plug_data:
    for item in plug_data:
        if item['code'] in ['cur_power', 'power']: live_power_w = item['value'] / 10.0
        if item['code'] in ['add_ele', 'total_forward_energy', 'energy_total']: total_kwh_accumulated = item['value'] 
live_power_kw = live_power_w / 1000.0

heater_data, heater_err = get_tuya_status(TUYA_HEATER_ID)
target_temp = 20; current_temp = 0; heater_on = False; heater_online = False
if heater_data:
    heater_online = True
    for item in heater_data:
        if item['code'] == 'temp_set': target_temp = item['value']
        if item['code'] == 'temp_current': current_temp = item['value']
        if item['code'] == 'switch': heater_on = item['value']

# --- UI START ---
selected_house = st.selectbox("Select Property", ["Main House", "Guest House"])
df, last_updated = fetch_data()

if df is None:
    st.error("Data Error")
else:
    tz = pytz.timezone('Europe/Stockholm')
    now = datetime.now(tz)
    st.caption(f"Last updated: {last_updated}")

    with st.expander("🧮 Calculators & Bill Estimator", expanded=True):
        tab1, tab2 = st.tabs(["Appliance Cost", "Invoice Predictor"])
        
        with tab1:
            st.info(f"Analysis for: **{selected_house}**")
            
            if selected_house == "Guest House":
                if live_power_w > 0:
                    st.success(f"🔌 **LIVE Power:** {live_power_w:.1f} W ({live_power_kw:.3f} kW)")
                else:
                    st.info(f"🔌 **Office Heater:** Idle (0 W)")

                st.markdown("---")
                st.subheader("🔥 Climate Control")
                if heater_online:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Room Temp", f"{current_temp}°C")
                    c2.metric("Target", f"{target_temp}°C")
                    c3.metric("State", "ON" if heater_on else "OFF", delta="Heating" if heater_on else "Off")
                    
                    sc1, sc2, sc3 = st.columns([1, 1, 2])
                    with sc1:
                        if st.button("❄️ -1°"):
                            send_tuya_command(TUYA_HEATER_ID, 'temp_set', target_temp - 1)
                            st.rerun()
                    with sc2:
                        if st.button("🔥 +1°"):
                            send_tuya_command(TUYA_HEATER_ID, 'temp_set', target_temp + 1)
                            st.rerun()
                    with sc3:
                        if st.button(f"Turn {'OFF' if heater_on else 'ON'}", use_container_width=True, type="primary" if not heater_on else "secondary"):
                            send_tuya_command(TUYA_HEATER_ID, 'switch', not heater_on)
                            st.rerun()
                else:
                    st.warning("Heater Offline")

                st.markdown("---")
                machine_options = ["Office Heater (Guest House)", "Sauna (2h)"]
            else:
                machine_options = ["Heaters (PAX)", "Dishwasher (1.5h)", "Washing Machine (2h)"]
            
            appliance = st.selectbox("Machine", machine_options)
            
            avg_price_total = df['Total Price'].mean() / 100
            usage_kw = 0.0; duration = 0.0

            if "Office Heater" in appliance:
                usage_kw = live_power_kw if live_power_kw > 0 else 1.0
                duration = 1.0
            elif "Heaters (PAX)" in appliance:
                num_heaters = st.slider("Heaters?", 1, 10, 5)
                usage_kw = num_heaters * 0.8; duration = 1.0
            elif "Sauna" in appliance: usage_kw = 6.0; duration=2.0
            elif "Dishwasher" in appliance: usage_kw = 1.2; duration=1.5
            elif "Washing" in appliance: usage_kw = 1.5; duration=2.0
            
            curr_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
            
            if not curr_row.empty:
                price_now = curr_row.iloc[0]['Total Price'] / 100
                cost_now = price_now * usage_kw * duration

                if "Office Heater" in appliance:
                    st.write(f"Run Rate NOW: **{cost_now:.2f} kr / hour**")
                    st.markdown(f"### 📉 Total Lifetime Cost")
                    if total_kwh_accumulated > 0:
                         total_kwh_real = total_kwh_accumulated / PLUG_SCALING_FACTOR
                         estimated_cost_accum = total_kwh_real * avg_price_total 
                         st.write(f"**{estimated_cost_accum:.2f} kr**")
                         st.caption(f"Based on Plug Counter: {total_kwh_real:.2f} kWh")
                    else:
                        st.caption("No history data available yet.")
                else:
                    st.write(f"Run **NOW**: **{cost_now:.2f} kr**")

        with tab2:
            st.subheader("🔮 Invoice Predictor")
            has_priskollen = st.checkbox("Include 'Priskollen' (49kr)?", value=True)
            fortum_fixed_calc = FORTUM_BASE_FEE + (FORTUM_PRISKOLLEN if has_priskollen else 0)
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("### 🏠 Main")
                main_kwh = st.number_input("kWh", value=1680)
                main_peak = st.number_input("Peak (kW)", value=7.9)
                
                # Grid Cost = Fixed + Transfer + Peak
                grid_cost = ELLEVIO_MONTHLY_FIXED + \
                            (main_kwh * ((ELLEVIO_TRANSFER_FEE_EX_VAT*1.25) + ENERGY_TAX_INC_VAT)/100) + \
                            (main_peak * ELLEVIO_PEAK_FEE_PER_KW)
                
                # Electricity Cost = Fixed + Spot + Markup
                # Note: This is a rough estimator. Real bill sums hourly.
                # We use a static average spot price for estimation (e.g. 70 öre)
                est_spot_price = 70.0 
                elec_cost = fortum_fixed_calc + \
                            (main_kwh * ((est_spot_price*1.25) + FORTUM_MARKUP_INC_VAT)/100)

                st.caption(f"Est: {grid_cost + elec_cost:.0f} kr")

            with col_b:
                st.markdown("### 🏚️ Guest")
                guest_kwh = st.number_input("Guest kWh", value=658)
                default_guest_peak = max(3.6, live_power_kw)
                guest_peak = st.number_input("Peak (kW)", value=default_guest_peak)
                
                g_grid = ELLEVIO_MONTHLY_FIXED + \
                         (guest_kwh * ((ELLEVIO_TRANSFER_FEE_EX_VAT*1.25) + ENERGY_TAX_INC_VAT)/100) + \
                         (guest_peak * ELLEVIO_PEAK_FEE_PER_KW)
                
                g_elec = fortum_fixed_calc + \
                         (guest_kwh * ((est_spot_price*1.25) + FORTUM_MARKUP_INC_VAT)/100)

                st.caption(f"Est: {g_grid + g_elec:.0f} kr")
            
            st.divider()
            st.metric("TOTAL FOR BOTH", f"{(grid_cost + elec_cost + g_grid + g_elec):.0f} kr")

    # --- DASHBOARD ---
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    if not current_row.empty:
        price = current_row.iloc[0]['Total Price']
        spot = current_row.iloc[0]['Spot Price']
        grid = (ELLEVIO_TRANSFER_FEE_EX_VAT * 1.25) + ENERGY_TAX_INC_VAT
        
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
    st.altair_chart(bars.properties(height=300), use_container_width=True)

    st.markdown("### 🎨 Signal Guide")
    c1, c2, c3 = st.columns(3)
    with c1: st.success("🟢 **SAFE**"); st.caption("Night / Wknd")
    with c2: st.warning("🟢 **CAUTION**"); st.caption("Day 07-20")
    with c3: st.error("🔴 **EXPENSIVE**"); st.caption("> 2.00 SEK")
