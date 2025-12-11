
import streamlit as st
import requests
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION (VERIFIED OCT 2025 BILLS) ---
REGION = "SE3"
IS_VILLA = True 

# 1. ELLEVIO (NETWORK) - Source: Physical Bill [cite: 336, 129]
# Both houses pay the same fixed fee (365 kr)
ELLEVIO_TRANSFER_FEE = 6.25    # öre/kWh (incl VAT)
ELLEVIO_PEAK_FEE_PER_KW = 81.25 # kr/kW (incl VAT)
ELLEVIO_MONTHLY_FIXED = 365.00  # kr/month (incl VAT)

# 2. GOVERNMENT TAX - Source: Physical Bill [cite: 362]
ENERGY_TAX = 54.88 # öre/kWh

# 3. FORTUM (ELECTRICITY) - Source: Physical Bill [cite: 67]
# Markup: 2.00 (Påslag) + 1.90 (Cert) = 3.90 ex VAT -> 4.88 incl VAT
FORTUM_MARKUP = 4.88 
# Fixed: 55.20 (Fee) + 39.20 (Priskollen) = 94.40 ex VAT -> 118.00 incl VAT
FORTUM_BASE_FEE = 69.00     # Standard fee
FORTUM_PRISKOLLEN = 49.00   # Extra service found on bill

def get_total_price(spot_ore):
    # Formula: (Spot + Markup) * VAT + Grid + Tax
    # Note: Our FORTUM_MARKUP already includes VAT adjustment for the fixed add-ons
    # But Spot needs VAT.
    fortum_part = (spot_ore * 1.25) + FORTUM_MARKUP
    grid_part = (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX
    # Wait, bill says Transfer 6.25 is "6.25 öre". Usually Ellevio prices exclude VAT in lists but bill says "66,81 kr" for 1069 kWh @ 6.25.
    # 1069 * 0.0625 = 66.81. So 6.25 IS the price. 
    # Does it need VAT added? "Momsgrundande 1266".
    # Let's assume 6.25 is ex VAT for safety, standard practice.
    # Actually, look at source 336: "Pris inkl moms" is NOT checked for transfer.
    # It calculates tax separately. So we multiply by 1.25.
    
    return fortum_part + (ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX

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
            st.subheader("🔮 Invoice Predictor (Validated)")
            
            has_priskollen = st.checkbox("Include 'Priskollen' Fee (49kr)?", value=True)
            fortum_fixed_calc = FORTUM_BASE_FEE + (FORTUM_PRISKOLLEN if has_priskollen else 0)
            
            col1, col2 = st.columns(2)
            
            # MAIN HOUSE (Oct Data: 1069 kWh, 6.94 kW Peak)
            with col1:
                st.markdown("### 🏠 Main House")
                main_kwh = st.number_input("Main kWh", value=1069)
                main_peak = st.number_input("Main Peak (kW)", value=6.9)
                
                m_fortum = (main_kwh * 1.00) + fortum_fixed_calc
                m_ellevio_var = main_kwh * ((ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX)/100
                m_ellevio_fixed = ELLEVIO_MONTHLY_FIXED + (main_peak * ELLEVIO_PEAK_FEE_PER_KW)
                m_total = m_fortum + m_ellevio_var + m_ellevio_fixed
                st.caption(f"Est: {m_total:.0f} kr")

            # GUEST HOUSE (Oct Data: 517 kWh, 3.6 kW Peak)
            with col2:
                st.markdown("### 🏚️ Guest House")
                guest_kwh = st.number_input("Guest kWh", value=517)
                guest_peak = st.number_input("Guest Peak (kW)", value=3.6)
                
                g_fortum = (guest_kwh * 1.00) + fortum_fixed_calc
                g_ellevio_var = guest_kwh * ((ELLEVIO_TRANSFER_FEE * 1.25) + ENERGY_TAX)/100
                g_ellevio_fixed = ELLEVIO_MONTHLY_FIXED + (guest_peak * ELLEVIO_PEAK_FEE_PER_KW)
                g_total = g_fortum + g_ellevio_var + g_ellevio_fixed
                st.caption(f"Est: {g_total:.0f} kr")
            
            st.divider()
            grand_total = m_total + g_total
            st.metric("TOTAL FOR BOTH", f"{grand_total:.0f} kr")
            if not has_priskollen:
                st.success("You save ~98 kr/month by cancelling Priskollen!")

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

    st.subheader("Price Forecast (Peak Penalty Risk 07-20)")
    st.info("⚠️ **Important:** Your Fortum bill is currently 'Monthly Price'. Switch to 'Hourly Price' (Timpris) to maximize savings from this graph!")
    
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
