import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz

# --- 2025 CONFIGURATION ---
REGION = "SE3"  # Stockholm / Middle Sweden

# 1. YOUR HOUSING TYPE (Change this to True if you live in a Villa/House)
IS_VILLA = True 

# 2. ELLEVIO GRID FEES (2025 Rules)
# Villa: Low transfer fee (~6 öre), but HIGH penalty for peaks (Effektavgift)
# Apartment: Higher transfer fee (~26 öre), usually no peak penalty
if IS_VILLA:
    ELLEVIO_TRANSFER_FEE = 6.0   # öre/kWh (approx for 2025 villa)
else:
    ELLEVIO_TRANSFER_FEE = 26.0  # öre/kWh (approx for 2025 apt)

# 3. GOVERNMENT TAX (2025 Law)
# Fixed at 54.88 öre incl VAT (43.9 ex VAT)
ENERGY_TAX = 54.88

# 4. FORTUM MARKUP (Calibrated from your Dec 2025 Invoice)
# This covers the gap between Spot Price and your actual Invoice (~106 öre)
# Includes VAT, Electricity Certificates, and likely "Miljöval" fee.
FORTUM_MARKUP = 17.5 

# --- FUNCTIONS ---
def get_total_price(spot_ore):
    """Calculates the REAL cost you pay per kWh."""
    # 1. Fortum Bill: (Spot + Markup) * VAT 25%
    # Note: If markup already includes VAT in our config, we adjust math.
    # Standard: ((Spot + Markup_Ex_VAT) * 1.25). 
    # Simplified for your calibration: Spot * 1.25 + Fixed_Addons
    fortum_part = (spot_ore * 1.25) + FORTUM_MARKUP
    
    # 2. Ellevio Bill: (Transfer * 1.25) + Tax
    # Tax (54.88) is already VAT-included in 2025 tables.
    ellevio_part = (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX
    
    return fortum_part + ellevio_part

@st.cache_data(ttl=3600)
def fetch_data():
    """Fetches today's and tomorrow's prices from API."""
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
            
    if not all_data:
        return None

    # Process data
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
            "BarColor": "red" if total_ore > 300 else "green" # The 3 SEK Rule
        })
    
    return pd.DataFrame(rows)

# --- PAGE LAYOUT ---
st.set_page_config(page_title="Power Monitor 2025", page_icon="⚡")
st.title("⚡ My Power Cost")

df = fetch_data()

if df is None:
    st.error("Could not fetch data. Try again later.")
else:
    # 1. CURRENT STATUS
    tz = pytz.timezone('Europe/Stockholm')
    now = datetime.now(tz)
    
    current_row = df[
        (df['Time'].dt.hour == now.hour) & 
        (df['Time'].dt.date == now.date())
    ]
    
    if not current_row.empty:
        price = current_row.iloc[0]['Total Price']
        spot = current_row.iloc[0]['Spot Price']
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("TOTAL YOU PAY", f"{price:.2f} öre", 
                     delta="- Cheap" if price < 150 else "+ Expensive",
                     delta_color="inverse")
        with col2:
            st.caption(f"Spot Price: {spot} öre")
            st.caption(f"Grid+Tax: {(ELLEVIO_TRANSFER_FEE*1.25 + ENERGY_TAX):.1f} öre")

    # 2. THE RED/GREEN CHART
    st.subheader("Next 24 Hours")
    
    # Filter: Show from 2 hours ago into the future
    start_view = now - timedelta(hours=2)
    chart_data = df[df['Time'] >= start_view]

    # Altair Chart for Custom Colors
    chart = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M', title='Hour')),
        y=alt.Y('Total Price', title='Öre / kWh'),
        # CONDITIONAL COLORING: Red if > 300, else Green
        color=alt.condition(
            alt.datum['Total Price'] > 300,
            alt.value('#ff4b4b'),  # Red
            alt.value('#00c853')   # Green
        ),
        tooltip=['Time', 'Total Price', 'Spot Price']
    ).properties(height=300)

    st.altair_chart(chart, use_container_width=True)

    # 3. WARNINGS
    if IS_VILLA:
        st.info("🏠 **VILLA MODE:** Remember the 'Effektavgift'. Running too many things at once costs extra, even if the price above is green!")
    
    with st.expander("Detailed Price List"):
        st.dataframe(df[['Time', 'Total Price', 'Spot Price']])
