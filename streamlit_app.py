import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION (VERIFIED OCT 2025 BILLS) ---
REGION = "SE3"
IS_VILLA = True 

# 1. ELLEVIO (NETWORK)
ELLEVIO_TRANSFER_FEE = 6.25    # öre/kWh
ELLEVIO_PEAK_FEE_PER_KW = 81.25 # kr/kW
ELLEVIO_MONTHLY_FIXED = 365.00  # kr/month

# 2. GOVERNMENT TAX
ENERGY_TAX = 54.88 # öre/kWh

# 3. FORTUM (ELECTRICITY)
FORTUM_MARKUP = 4.88  # Markup + Cert (incl VAT)
FORTUM_BASE_FEE = 69.00
FORTUM_PRISKOLLEN = 49.00

def get_total_price(spot_ore):
    # (Spot * 1.25 VAT) + Fortum Markup + (Grid Transfer * 1.25 VAT) + Energy Tax
    fortum_part = (spot_ore * 1.25) + FORTUM_MARKUP
    grid_part = (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX
    return fortum_part + grid_part

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

# --- PROPERTY SELECTOR ---
selected_house = st.selectbox("Select Property", ["Main House", "Guest House"])

df = fetch_data()

if df is None:
    st.error("Could not fetch data.")
else:
    tz = pytz.timezone('Europe/Stockholm')
    now = datetime.now(tz)

    with st.expander("🧮 Calculators & Bill Estimator", expanded=False):
        
        tab1, tab2 = st.tabs(["Appliance Cost", "Invoice Predictor"])
        
        with tab1:
            st.info(f"Analysis for: **{selected_house}**")
            appliance = st.selectbox("Machine", ["Heaters (PAX)", "Sauna (2h)", "Dishwasher (1.5h)", "Washing Machine (2h)"])
            
            if "Heaters" in appliance:
                num_heaters = st.slider("Heaters running?", 1, 10, 5)
                kwh_load = num_heaters * 0.8; duration = 1.0; label="per hour"
            elif "Sauna" in appliance: kwh_load = 6.0; duration=2; label="total"
            elif "Dishwasher" in appliance: kwh_load = 1.2; duration=1.5; label="total"
            elif "Washing" in appliance: kwh_load = 1.5; duration=2; label="total"
            
            curr_row = df[(df['Time'].dt.hour == now.hour) & (df['Time'].dt.date == now.date())]
            if not curr_row.empty:
                cost = (curr_row.iloc[0]['Total Price'] / 100) * kwh_load * duration
                st.write(f"Run **NOW**: **{cost:.2f} kr** ({label})")

        with tab2:
            st.subheader("🔮 Invoice Predictor")
            has_priskollen = st.checkbox("Include 'Priskollen' Fee (49kr)?", value=True)
            fortum_fixed_calc = FORTUM_BASE_FEE + (FORTUM_PRISKOLLEN if has_priskollen else 0)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### 🏠 Main")
                main_kwh = st.number_input("kWh", value=1069)
                main_peak = st.number_input("Peak (kW)", value=6.9)
                m_total = (main_kwh * 1.00) + fortum_fixed_calc + \
                          (main_kwh * ((ELLEVIO_TRANSFER_FEE*1.25)+ENERGY_TAX)/100) + \
                          (ELLEVIO_MONTHLY_FIXED + (main_peak * ELLEVIO_PEAK_FEE_PER_KW))
                st.caption(f"Est: {m_total:.0f} kr")

            with col2:
                st.markdown("### 🏚️ Guest")
                guest_kwh = st.number_input("kWh", value=517)
                guest_peak = st.number_input("Peak (kW)", value=3.6)
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
    
    chart = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X('Time', axis=alt.Axis(format='%H:%M')),
        y=alt.Y('Total Price'),
        color=alt.Color('Color', scale=None),
        opacity=alt.Opacity('Opacity', scale=None),
        tooltip=['Time', 'Total Price']
    ).properties(height=300)
    st.altair_chart(chart, use_container_width=True)

    # --- THE COLOR MATRIX (LEGEND) ---
    st.markdown("### 🎨 Signal Guide")
    
    # Create 3 columns for the Matrix
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.success("🟢 **SAFE ZONE**")
        st.caption("Night / Weekend")
        st.markdown("- **Price:** Low\n- **Peak Penalty:** NO\n- **Action:** Run Everything!")
        
    with c2:
        st.warning("🟢 **CAUTION**")
        st.caption("Wkday 07:00–20:00")
        st.markdown("- **Price:** Low\n- **Peak Penalty:** **YES**\n- **Action:** One machine at a time.")
        
    with c3:
        st.error("🔴 **EXPENSIVE**")
        st.caption("Price > 2.00 SEK")
        st.markdown("- **Price:** High\n- **Peak Penalty:** Depends\n- **Action:** Wait.")
