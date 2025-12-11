import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION ---
REGION = "SE3"
IS_VILLA = True 

# FEES (2025)
if IS_VILLA:
    ELLEVIO_TRANSFER_FEE = 6.25 
    # Ellevio High Load Fee (Höglast) often ~81 kr/kW/month in winter
    # Update this if you find exact "Effektavgift" price on your bill.
    ELLEVIO_PEAK_FEE_PER_KW = 81.0 
else:
    ELLEVIO_TRANSFER_FEE = 26.0
    ELLEVIO_PEAK_FEE_PER_KW = 0

ENERGY_TAX = 54.88
FORTUM_MARKUP = 17.5 

# --- FUNCTIONS ---
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
        rows.append({
            "Time": start,
            "Hour": start.hour,
            "Total Price": round(total_ore, 2),
            "Spot Price": round(spot_ore, 2),
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
        appliance = st.selectbox("Machine", ["Washing Machine (2h)", "Tumble Dryer (1.5h)", "Sauna (2h)", "Electric Car (4h)"])
        
        # Wattage estimates
        if "Washing" in appliance: kwh_load = 1.5; duration=2
        elif "Dryer" in appliance: kwh_load = 2.5; duration=1.5
        elif "Sauna" in appliance: kwh_load = 6.0; duration=2
        elif "Car" in appliance: kwh_load = 11.0; duration=4
        
        tz = pytz.timezone('Europe/Stockholm')
        now = datetime.now(tz)
        current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
        
        if not current_row.empty:
            curr_price = current_row.iloc[0]['Total Price'] / 100 # to KR
            cost_now = curr_price * kwh_load * duration
            st.write(f"Run **NOW**: approx **{cost_now:.2f} kr**")
        
        # Find Cheapest Time in next 24h
        future_df = df[df['Time'] >= (now - timedelta(hours=1))].head(24)
        min_price_row = future_df.loc[future_df['Total Price'].idxmin()]
        best_time = min_price_row['Time']
        best_price = min_price_row['Total Price'] / 100
        cost_best = best_price * kwh_load * duration
        
        st.success(f"Run at **{best_time.strftime('%H:%M')}**: approx **{cost_best:.2f} kr**")
        st.caption(f"Difference: {cost_now - cost_best:.2f} kr")

        st.divider()

        # 2. EFFEKTAVGIFT ESTIMATOR
        if IS_VILLA:
            st.subheader("🏠 Peak Penalty (Effekt)")
            st.caption("How high is your peak this month?")
            peak_kw = st.slider("Your Max Peak (kW)", 0, 20, 8)
            monthly_fee = peak_kw * ELLEVIO_PEAK_FEE_PER_KW
            st.metric("Monthly Penalty", f"{monthly_fee:.0f} kr")
            st.caption(f"Based on ~{ELLEVIO_PEAK_FEE_PER_KW} kr/kW")

    # --- MAIN DASHBOARD ---
    # (Same as before, simplified for 'wide' layout)
    now = datetime.now(tz)
    current_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
    
    if not current_row.empty:
        price = current_row.iloc[0]['Total Price']
        col1, col2, col3 = st.columns(3)
        col1.metric("Current Price", f"{price:.2f} öre", delta_color="inverse", 
                    delta="- Low" if price < 150 else "+ High")
        col2.metric("Spot Price", f"{current_row.iloc[0]['Spot Price']} öre")
        col3.metric("Grid + Tax", f"{(ELLEVIO_TRANSFER_FEE*1.25 + ENERGY_TAX):.1f} öre")

    st.subheader("Price Forecast (24h)")
    start_view = now - timedelta(hours=2)
    chart_data = df[df['Time'] >= start_view]
    
    chart = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M')),
        y=alt.Y('Total Price'),
        color=alt.Color('Color', scale=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=400)
    st.altair_chart(chart, use_container_width=True)
