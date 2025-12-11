import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION ---
REGION = "SE3"              # SE3 = Stockholm, SE4 = Malmö, etc.
# Your Specific Fees (Update these!)
FORTUM_MARKUP = 23.9        # Your calculated Fortum markup
ELLEVIO_TRANSFER = 26.0     # Grid transfer fee
ENERGY_TAX = 54.88          # Energy tax

# --- PAGE SETUP ---
st.set_page_config(page_title="Power Monitor", page_icon="⚡")
st.title("⚡ Sweden Power Price")

# --- FUNCTIONS ---
def get_total_price(spot_ore):
    """Calculates the total cost including all fees and VAT."""
    # 1. Fortum (Spot + Markup) * VAT
    fortum_part = (spot_ore + FORTUM_MARKUP) * 1.25
    
    # 2. Ellevio (Transfer * VAT) + Tax
    # Note: Check your bill if Tax is VAT-exempt or not. Usually Tax is 54.88 incl VAT.
    # We will assume standard formula: (Transfer * 1.25) + Tax
    ellevio_part = (ELLEVIO_TRANSFER * 1.25) + ENERGY_TAX
    
    return fortum_part + ellevio_part

@st.cache_data(ttl=3600)  # Cache data for 1 hour so it loads fast
def fetch_data():
    """Fetches today's and tomorrow's prices."""
    today = datetime.now(pytz.timezone('Europe/Stockholm'))
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

    # Process data into a clean DataFrame
    rows = []
    for hour in all_data:
        start = datetime.fromisoformat(hour['time_start'])
        spot_ore = hour['SEK_per_kWh'] * 100
        total_ore = get_total_price(spot_ore)
        
        rows.append({
            "Time": start,
            "Hour": start.hour,
            "Spot Price": spot_ore,
            "Total Price": total_ore,
            "Color": "red" if total_ore > 200 else "green" # Simple color logic
        })
    
    return pd.DataFrame(rows)

# --- MAIN APP LOGIC ---
df = fetch_data()

if df is None:
    st.error("Could not fetch data. Try again later.")
else:
    # 1. FIND CURRENT PRICE
    now = datetime.now(pytz.timezone('Europe/Stockholm'))
    current_hour = now.hour
    today_date = now.date()
    
    # Filter for the current specific hour row
    current_row = df[
        (df['Time'].dt.hour == current_hour) & 
        (df['Time'].dt.date == today_date)
    ]
    
    if not current_row.empty:
        price = current_row.iloc[0]['Total Price']
        
        # Display Big Metric
        st.metric(
            label=f"Current Price ({current_hour}:00 - {current_hour+1}:00)",
            value=f"{price:.2f} öre",
            delta="High Price" if price > 200 else "Good Price",
            delta_color="inverse"
        )
    
    # 2. SHOW CHART
    st.subheader("Price Trend (Next 24h)")
    
    # Filter for future hours only (optional, or show whole day)
    chart_data = df[df['Time'] >= (now - timedelta(hours=2))]
    
    # Create a bar chart
    st.bar_chart(chart_data, x="Time", y="Total Price")

    # 3. ADVICE
    st.subheader("💡 Recommendation")
    if price < 150:
        st.success("✅ **GO!** It is cheap right now. Run the washer.")
    elif price < 250:
        st.warning("⚠️ **WAIT.** Price is okay, but maybe wait for night?")
    else:
        st.error("🛑 **STOP.** Very expensive. Turn off unnecessary lights.")

    # 4. DATA TABLE (Hidden by default)
    with st.expander("See detailed table"):
        st.dataframe(df[['Time', 'Total Price', 'Spot Price']])