import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz

# --- 2025 CONFIGURATION ---
REGION = "SE3"  # Stockholm / Middle Sweden

# 1. YOUR HOUSING TYPE (Set True if you live in a Villa/Rowhouse)
IS_VILLA = True 

# 2. ELLEVIO GRID FEES (2025 Rules)
if IS_VILLA:
    ELLEVIO_TRANSFER_FEE = 6.25  # öre/kWh (2025 Villa rate)
else:
    ELLEVIO_TRANSFER_FEE = 26.0  # öre/kWh (Standard Apartment rate)

# 3. GOVERNMENT TAX (2025 Law)
ENERGY_TAX = 54.88

# 4. FORTUM MARKUP (Calibrated from your Dec 2025 Invoice)
FORTUM_MARKUP = 17.5 

# --- FUNCTIONS ---
def get_total_price(spot_ore):
    """Calculates the REAL cost you pay per kWh."""
    # 1. Fortum: (Spot * 1.25 VAT) + Markup
    fortum_part = (spot_ore * 1.25) + FORTUM_MARKUP
    
    # 2. Ellevio: (Transfer * 1.25 VAT) + Tax
    ellevio_part = (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX
    
    return fortum_part + ellevio_part

@st.cache_data(ttl=3600)
def fetch_data():
    """Fetches prices and sets color based on the 2 SEK limit."""
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

    rows = []
    for hour in all_data:
        start = datetime.fromisoformat(hour['time_start'])
        spot_ore = hour['SEK_per_kWh'] * 100
        total_ore = get_total_price(spot_ore)
        
        # --- THE COLOR LOGIC ---
        # If price > 200 öre (2 SEK), color it RED. Otherwise GREEN.
        bar_color = "#ff4b4b" if total_ore > 200 else "#00c853"
        
        rows.append({
            "Time": start,
            "Hour": start.hour,
            "Total Price": round(total_ore, 2),
            "Spot Price": round(spot_ore, 2),
            "Color": bar_color
        })
    
    return pd.DataFrame(rows)

# --- PAGE LAYOUT ---
st.set_page_config(page_title="Power Cost 2025", page_icon="⚡")
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

    # 2. THE CHART (Red Bars > 200 öre)
    st.subheader("Next 24 Hours")
    
    start_view = now - timedelta(hours=2)
    chart_data = df[df['Time'] >= start_view]

    chart = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M', title='Hour')),
        y=alt.Y('Total Price', title='Öre / kWh'),
        color=alt.Color('Color', scale=None), 
        tooltip=['Time', 'Total Price', 'Spot Price']
    ).properties(height=300)

    st.altair_chart(chart, use_container_width=True)

    # 3. WARNINGS
    if IS_VILLA:
        st.info("🏠 **VILLA MODE:** Low transfer fee, but watch out for PEAKS (running everything at once)!")
    
    with st.expander("Detailed Price List"):
        st.dataframe(df[['Time', 'Total Price', 'Spot Price']])
