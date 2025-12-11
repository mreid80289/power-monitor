import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION ---
REGION = "SE3"
IS_VILLA = True 

# 2025 FEES (Standard Ellevio Villa)
ELLEVIO_TRANSFER_FEE = 6.25   
ELLEVIO_PEAK_FEE_PER_KW = 81.25 
ELLEVIO_MONTHLY_FIXED = 292.0 

ENERGY_TAX = 54.88 
FORTUM_MARKUP = 17.5 
FORTUM_MONTHLY_FIXED = 49.0 

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
        
        tab1, tab2 = st.tabs(["Appliance Cost", "Invoice Predictor"])
        
        # TAB 1: APPLIANCE
        with tab1:
            st.subheader("Vad kostar det?")
            # Updated List with Locations
            appliance = st.selectbox("Select Machine", [
                "Sauna [Guest House] (6kW)", 
                "Heaters [Main House] (PAX)", 
                "Heaters [Guest House] (PAX)",
                "Washing Machine [Main House]",
                "Dishwasher [Main House]"
            ])
            
            # Logic
            if "Sauna" in appliance: kwh_load = 6.0; duration=2.0; label="total"; house="Guest"
            elif "Dishwasher" in appliance: kwh_load = 1.2; duration=1.5; label="total"; house="Main"
            elif "Washing" in appliance: kwh_load = 1.5; duration=2.0; label="total"; house="Main"
            elif "Heaters" in appliance:
                num_heaters = st.slider("Number of Heaters?", 1, 10, 3)
                kwh_load = num_heaters * 0.8
                duration = 1.0; label="per hour"
                house = "Guest" if "Guest" in appliance else "Main"
            
            curr_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
            if not curr_row.empty:
                cost = (curr_row.iloc[0]['Total Price'] / 100) * kwh_load * duration
                st.write(f"Run **NOW**: **{cost:.2f} kr** ({label})")
                
                # Context-Aware Warnings
                if "Sauna" in appliance:
                    st.info(f"ℹ️ **Note:** This hits the **{house} House** bill. It will create a 6kW Peak (~487 kr) if run 07:00-20:00 weekdays.")
                elif kwh_load > 3.0:
                    st.warning(f"🔥 **Watch out:** This adds {kwh_load:.1f} kW to the **{house} House** peak!")

        # TAB 2: DUAL BILL SIMULATOR
        with tab2:
            st.subheader("🔮 Full Property Invoice Predictor")
            
            col1, col2 = st.columns(2)
            
            # MAIN HOUSE INPUTS
            with col1:
                st.markdown("### 🏠 Main House")
                main_kwh = st.number_input("Main kWh", value=1069)
                main_peak = st.number_input("Main Peak (kW)", value=7.8)
                
                m_fortum = (main_kwh * 1.00) + FORTUM_MONTHLY_FIXED
                m_ellevio_var = main_kwh * ((ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX)/100
                m_ellevio_fixed = ELLEVIO_MONTHLY_FIXED + (main_peak * ELLEVIO_PEAK_FEE_PER_KW)
                m_total = m_fortum + m_ellevio_var + m_ellevio_fixed
                st.caption(f"Est: {m_total:.0f} kr")

            # GUEST HOUSE INPUTS
            with col2:
                st.markdown("### 🏚️ Guest House")
                guest_kwh = st.number_input("Guest kWh", value=517)
                # Default guest peak 4.5kW (Oct historical)
                guest_peak = st.number_input("Guest Peak (kW)", value=4.5)
                
                g_fortum = (guest_kwh * 1.00) + FORTUM_MONTHLY_FIXED
                g_ellevio_var = guest_kwh * ((ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX)/100
                g_ellevio_fixed = ELLEVIO_MONTHLY_FIXED + (guest_peak * ELLEVIO_PEAK_FEE_PER_KW)
                g_total = g_fortum + g_ellevio_var + g_ellevio_fixed
                st.caption(f"Est: {g_total:.0f} kr")
            
            st.divider()
            grand_total = m_total + g_total
            st.metric("TOTAL FOR BOTH HOUSES", f"{grand_total:.0f} kr")

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
    st.caption("Solid Bars = Peak Penalty Risk (07-20). Faded Bars = Safe Time.")
    
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
