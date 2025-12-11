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
    # Villa Transfer Fee: 6.25 öre/kWh
    ELLEVIO_TRANSFER_FEE = 6.25 
    # Peak Penalty (Effektavgift): 81.25 kr/kW
    ELLEVIO_PEAK_FEE_PER_KW = 81.25 
else:
    # Apartment Transfer Fee: ~26 öre/kWh
    ELLEVIO_TRANSFER_FEE = 26.0
    ELLEVIO_PEAK_FEE_PER_KW = 0

# 2. GOVERNMENT TAX (2025 Law)
ENERGY_TAX = 54.88

# 3. FORTUM MARKUP (Calibrated)
FORTUM_MARKUP = 17.5 

# --- FUNCTIONS ---
def get_total_price(spot_ore):
    # Fortum Part: (Spot * 1.25) + Markup
    fortum = (spot_ore * 1.25) + FORTUM_MARKUP
    # Grid Part: (Transfer * 1.25) + Tax (Tax already has VAT)
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
            # RED if > 2.00 SEK, GREEN otherwise
            "Color": "#ff4b4b" if total_ore > 200 else "#00c853"
        })
    return pd.DataFrame(rows)

# --- PAGE LAYOUT ---
st.set_page_config(page_title="Power Monitor Pro", page_icon="⚡", layout="wide")
st.title("⚡ Power Monitor Pro")

df = fetch_data()

if df is None:
    st.error("Could not fetch data.")
else:
    # --- SIDEBAR: CALCULATORS ---
    with st.sidebar:
        st.header("🧮 Calculators")
        
        # 1. APPLIANCE COST
        st.subheader("Vad kostar det?")
        
        # UPDATED LIST: Added "Whole House Heating"
        appliance = st.selectbox("Machine", [
            "Whole House Heating (1h)", 
            "Sauna (2h)",
            "Dishwasher (1.5h)", 
            "Washing Machine (2h)", 
            "Tumble Dryer (1.5h)"
        ])
        
        # UPDATED LOGIC FOR PAX HEATERS
        if "Heating" in appliance: 
            # Est: 15 radiators x 800W approx (conservative peak)
            kwh_load = 10.0; duration=1.0 
        elif "Sauna" in appliance: kwh_load = 6.0; duration=2
        elif "Dishwasher" in appliance: kwh_load = 1.2; duration=1.5
        elif "Washing" in appliance: kwh_load = 1.5; duration=2
        elif "Dryer" in appliance: kwh_load = 2.5; duration=1.5
        
        tz = pytz.timezone('Europe/Stockholm')
        now = datetime.now(tz)
        
        # Find Cheapest Time in next 24h
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
            st.write(f"Run **NOW**: approx **{cost_now:.2f} kr**")
            
            if "Heating" in appliance:
                st.warning("🔥 **Warning:** If all heaters turn on at once (e.g. cold morning), you create a massive 10kW Peak!")
            else:
                st.success(f"Best Time: **{best_time.strftime('%H:%M')}**\nCost: **{cost_best:.2f} kr**")
        
        st.divider()

        # 2. EFFEKTAVGIFT ESTIMATOR
        if IS_VILLA:
            st.subheader("🏠 Peak Penalty (Effekt)")
            st.caption("How high is your peak (kW)?")
            # Increased slider max to 25kW because Direct Electric heating pushes peaks higher
            peak_kw = st.slider("Max kW Peak", 0, 25, 12)
            monthly_fee = peak_kw * ELLEVIO_PEAK_FEE_PER_KW
            st.metric("Penalty Cost", f"{monthly_fee:.0f} kr", help="Charged monthly based on average of top 3 peaks.")

    # --- MAIN DASHBOARD ---
    now = datetime.now(tz)
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    
    if not current_row.empty:
        price = current_row.iloc[0]['Total Price']
        spot = current_row.iloc[0]['Spot Price']
        grid_tax = (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Current Price", f"{price:.2f} öre", delta_color="inverse", 
                    delta="- Low" if price < 150 else "+ High")
        col2.metric("Spot Price", f"{spot} öre")
        col3.metric("Grid + Tax", f"{grid_tax:.1f} öre")

    st.subheader("Price Forecast (24h)")
    
    if IS_VILLA:
        st.info("🏠 **VILLA MODE:** You have Direct Electric Heating. Avoid lowering temp at night—reheating in the morning causes expensive Peaks!")

    start_view = now - timedelta(hours=2)
    chart_data = df[df['Time'] >= start_view]
    
    chart = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M')),
        y=alt.Y('Total Price'),
        color=alt.Color('Color', scale=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=400)
    st.altair_chart(chart, use_container_width=True)
