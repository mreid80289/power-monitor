import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION ---
REGION = "SE3"
IS_VILLA = True 

# 2025 FEES
if IS_VILLA:
    ELLEVIO_TRANSFER_FEE = 6.25   #
    ELLEVIO_PEAK_FEE_PER_KW = 81.25 #
    ELLEVIO_MONTHLY_FIXED = 292.0 #
else:
    ELLEVIO_TRANSFER_FEE = 26.0
    ELLEVIO_PEAK_FEE_PER_KW = 0
    ELLEVIO_MONTHLY_FIXED = 90.0

ENERGY_TAX = 54.88 #
FORTUM_MARKUP = 17.5 
FORTUM_MONTHLY_FIXED = 49.0 # Standard Fortum fee

def get_total_price(spot_ore):
    return (spot_ore * 1.25) + FORTUM_MARKUP + (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX

@st.cache_data(ttl=3600)
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
            
    if not all_data: return None

    rows = []
    for hour in all_data:
        start = datetime.fromisoformat(hour['time_start'])
        spot_ore = hour['SEK_per_kWh'] * 100
        total_ore = get_total_price(spot_ore)
        
        # Danger Zone: Weekdays 07-20
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
    return pd.DataFrame(rows)

st.set_page_config(page_title="Power Monitor Pro", page_icon="⚡", layout="centered")
st.title("⚡ Power Monitor Pro")

df = fetch_data()

if df is None:
    st.error("Could not fetch data.")
else:
    tz = pytz.timezone('Europe/Stockholm')
    now = datetime.now(tz)

    with st.expander("🧮 Calculators & Bill Estimator", expanded=False):
        
        # TAB 1: APPLIANCES
        tab1, tab2 = st.tabs(["Appliance Cost", "Bill Simulator"])
        
        with tab1:
            st.subheader("Vad kostar det?")
            appliance = st.selectbox("Machine", ["Heaters (PAX)", "Sauna (2h)", "Dishwasher (1.5h)", "Washing Machine (2h)"])
            
            if "Heaters" in appliance:
                num_heaters = st.slider("Heaters running?", 1, 10, 5)
                kwh_load = num_heaters * 0.8
                duration = 1.0; label="per hour"
            elif "Sauna" in appliance: kwh_load = 6.0; duration=2; label="total"
            elif "Dishwasher" in appliance: kwh_load = 1.2; duration=1.5; label="total"
            elif "Washing" in appliance: kwh_load = 1.5; duration=2; label="total"
            
            curr_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
            if not curr_row.empty:
                cost = (curr_row.iloc[0]['Total Price'] / 100) * kwh_load * duration
                st.write(f"Run **NOW**: **{cost:.2f} kr** ({label})")
        
        # TAB 2: BILL SIMULATOR (FORENSIC TOOL)
        with tab2:
            st.subheader("🔮 Monthly Bill Predictor")
            st.caption("Enter your monthly stats to predict the invoice.")
            
            col_a, col_b = st.columns(2)
            with col_a:
                est_kwh = st.number_input("Total kWh", value=1069)
            with col_b:
                est_peak = st.number_input("Peak (kW)", value=7.8)
            
            # MATH
            # 1. Fortum Variable: ~1.00 kr/kWh (Based on your bills)
            fortum_var = est_kwh * 1.00 
            fortum_fixed = FORTUM_MONTHLY_FIXED
            
            # 2. Ellevio Variable
            ellevio_trans = est_kwh * (ELLEVIO_TRANSFER_FEE/100 * 1.25)
            ellevio_tax = est_kwh * (ENERGY_TAX/100)
            
            # 3. Ellevio Fixed/Peak
            ellevio_fixed = ELLEVIO_MONTHLY_FIXED
            ellevio_peak = est_peak * ELLEVIO_PEAK_FEE_PER_KW
            
            total_fortum = fortum_var + fortum_fixed
            total_ellevio = ellevio_trans + ellevio_tax + ellevio_fixed + ellevio_peak
            grand_total = total_fortum + total_ellevio
            
            st.divider()
            st.write(f"**Fortum Bill:** {total_fortum:.0f} kr")
            st.write(f"**Ellevio Bill:** {total_ellevio:.0f} kr (Peak Cost: {ellevio_peak:.0f} kr)")
            st.success(f"**TOTAL PREDICTION:** {grand_total:.0f} kr")

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

    st.subheader("Price Forecast (High Load Highlighted)")
    
    start_view = now - timedelta(hours=2)
    chart_data = df[df['Time'] >= start_view]
    
    chart = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M')),
        y=alt.Y('Total Price'),
        color=alt.Color('Color', scale=None),
        opacity=alt.Opacity('Opacity', scale=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=300)
    st.altair_chart(chart, use_container_width=True)
