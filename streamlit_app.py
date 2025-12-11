import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION (CALIBRATED DEC 2025) ---
REGION = "SE3"  # Stockholm
IS_VILLA = True 

# 1. ELLEVIO GRID FEES (Official 2025 Rates)
if IS_VILLA:
    ELLEVIO_TRANSFER_FEE = 6.25 
    ELLEVIO_PEAK_FEE_PER_KW = 81.25 
else:
    ELLEVIO_TRANSFER_FEE = 26.0
    ELLEVIO_PEAK_FEE_PER_KW = 0

# 2. GOVERNMENT TAX (2025 Law)
ENERGY_TAX = 54.88

# 3. FORTUM MARKUP (Calibrated)
FORTUM_MARKUP = 17.5 

# --- FUNCTIONS ---
def get_total_price(spot_ore):
    fortum = (spot_ore * 1.25) + FORTUM_MARKUP
    grid = (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX
    return fortum + grid

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
        rows.append({
            "Time": start,
            "Hour": start.hour,
            "Total Price": round(total_ore, 2),
            "Spot Price": round(spot_ore, 2),
            "Color": "#ff4b4b" if total_ore > 200 else "#00c853"
        })
    return pd.DataFrame(rows)

# --- PAGE LAYOUT ---
st.set_page_config(page_title="Power Monitor Pro", page_icon="⚡", layout="centered")
st.title("⚡ Power Monitor Pro")

df = fetch_data()

if df is None:
    st.error("Could not fetch data.")
else:
    tz = pytz.timezone('Europe/Stockholm')
    now = datetime.now(tz)

    # --- CALCULATORS ---
    with st.expander("🧮 Calculators (Click to Open)", expanded=False):
        
        # 1. APPLIANCE COST
        st.subheader("Vad kostar det?")
        
        # Base List
        base_options = ["Heaters (PAX Radiators)", "Sauna (2h)", "Dishwasher (1.5h)", "Washing Machine (2h)", "Tumble Dryer (1.5h)"]
        appliance = st.selectbox("Select Machine", base_options)
        
        # DYNAMIC LOGIC
        if "Heaters" in appliance:
            # Show a slider ONLY if Heaters is selected
            num_heaters = st.slider("Number of Heaters running?", 1, 5, 3)
            # Estimate: 0.8 kW (800W) per heater
            kwh_load = num_heaters * 0.8
            duration = 1.0 # Per hour cost
            time_label = "per hour"
        
        elif "Sauna" in appliance: kwh_load = 6.0; duration=2; time_label = "total"
        elif "Dishwasher" in appliance: kwh_load = 1.2; duration=1.5; time_label = "total"
        elif "Washing" in appliance: kwh_load = 1.5; duration=2; time_label = "total"
        elif "Dryer" in appliance: kwh_load = 2.5; duration=1.5; time_label = "total"
        
        # Find Cheapest Time
        future_df = df[df['Time'] >= (now - timedelta(hours=1))].head(24)
        min_price_row = future_df.loc[future_df['Total Price'].idxmin()]
        best_time = min_price_row['Time']
        best_price = min_price_row['Total Price'] / 100
        cost_best = best_price * kwh_load * duration
        
        # Find Cost NOW
        current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
        if not current_row.empty:
            curr_price = current_row.iloc[0]['Total Price'] / 100
            cost_now = curr_price * kwh_load * duration
            
            st.write(f"Run **NOW**: approx **{cost_now:.2f} kr** ({time_label})")
            
            # Peak Warning for Heaters
            if "Heaters" in appliance and num_heaters >= 4:
                st.warning(f"🔥 **Watch out:** {num_heaters} heaters = {kwh_load:.1f} kW load. Don't run the sauna at the same time!")
            else:
                st.success(f"Best Time: **{best_time.strftime('%H:%M')}** ({cost_best:.2f} kr)")
        
        st.divider()

        # 2. EFFEKTAVGIFT ESTIMATOR
        if IS_VILLA:
            st.subheader("🏠 Peak Penalty (Effekt)")
            peak_kw = st.slider("Max kW Peak", 0, 25, 12)
            monthly_fee = peak_kw * ELLEVIO_PEAK_FEE_PER_KW
            st.metric("Penalty Cost", f"{monthly_fee:.0f} kr")

    # --- MAIN DASHBOARD ---
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    
    if not current_row.empty:
        price = current_row.iloc[0]['Total Price']
        spot = current_row.iloc[0]['Spot Price']
        grid_tax = (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Current Price", f"{price:.2f} öre", delta_color="inverse", 
                    delta="- Low" if price < 150 else "+ High")
        with col2:
             st.caption(f"Spot: {spot} öre")
             st.caption(f"Grid+Tax: {grid_tax:.1f} öre")

    st.subheader("Price Forecast (24h)")
    
    if IS_VILLA:
        st.info("🏠 **VILLA TIP:** Avoid turning on all 5 heaters at exactly 07:00. Stagger them or keep a steady temp!")

    start_view = now - timedelta(hours=2)
    chart_data = df[df['Time'] >= start_view]
    
    chart = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M')),
        y=alt.Y('Total Price'),
        color=alt.Color('Color', scale=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=300)
    st.altair_chart(chart, use_container_width=True)
