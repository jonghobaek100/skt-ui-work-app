import streamlit as st
import pandas as pd
import requests
from geopy.distance import geodesic
import folium
from streamlit_folium import folium_static
from folium import Circle, PolyLine
import openai
import datetime
import pytz
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import subprocess

def upgrade_openai_library():
    try:
        result = subprocess.run(["pip", "install", "--upgrade", "openai"], capture_output=True, text=True, check=True)
        st.success("openai 라이브러리가 성공적으로 업그레이드되었습니다!")
        st.text(result.stdout)
    except subprocess.CalledProcessError as e:
        st.error("openai 업그레이드 중 오류가 발생했습니다.")
        st.text(e.stderr)

# API keys and URLs
NAVER_CLIENT_ID = os.getenv('NAVER_CLIENT_ID')
NAVER_CLIENT_SECRET = os.getenv('NAVER_CLIENT_SECRET')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
WEATHER_BASE_URL = os.getenv('WEATHER_BASE_URL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai.api_key = OPENAI_API_KEY

# Global variables
seoul_tz = pytz.timezone('Asia/Seoul')

# Function to get GPS coordinates from address
def get_gps_from_address(address):
    url = "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode"
    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET
    }
    params = {"query": address}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        result = response.json()
        if result['meta']['totalCount'] > 0:
            lat = result['addresses'][0]['y']
            lon = result['addresses'][0]['x']
            return float(lat), float(lon)
    return None

# Function to get weather info
def get_weather_info(latitude, longitude):
    now = datetime.datetime.now(seoul_tz) - datetime.timedelta(hours=1)
    base_date = now.strftime("%Y%m%d")
    base_time = now.strftime("%H00")
    nx, ny = 55, 127  # Placeholder coordinates
    params = {
        "serviceKey": WEATHER_API_KEY,
        "numOfRows": 10,
        "pageNo": 1,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }
    response = requests.get(WEATHER_BASE_URL, params=params)
    if response.status_code == 200:
        return response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
    return []

# Function to call OpenAI for fire spread prediction
def get_fire_spread_prediction(gps_coordinates, weather_info, fire_time):
    import json

    system_instruction = (
        "You are an expert in fire spread prediction. "
        "Using the provided fire location, time, and weather data, predict the fire spread areas for 1, 2, and 3 hours later. "
        "Return the predictions as a JSON object with keys for each time step, and values containing the center coordinates (lat, lon) and radius (in meters)."
    )
    user_instruction = (
        f"Fire Location: {gps_coordinates}\n"
        f"Fire Time: {fire_time}\n"
        f"Weather Data: {weather_info}\n"
        "Predict the spread of fire as described."
    )
    response = openai.Completion.create(
        engine="gpt-4",
        prompt=f"{system_instruction}\n{user_instruction}",
        temperature=0.5,
        max_tokens=1000
    )
    return json.loads(response.choices[0].text.strip())

# Function to filter facilities within a radius
def filter_facilities(data, gps_coordinates, radius):
    data['distance'] = data['공간위치G'].apply(
        lambda geom: geodesic(gps_coordinates, (float(geom.split()[1]), float(geom.split()[0]))).meters
    )
    return data[data['distance'] <= radius]

# Function to display map with fire spread and facilities
def display_fire_map(gps_coordinates, predictions, filtered_data):
    m = folium.Map(location=gps_coordinates, zoom_start=14)

    # Fire location
    folium.Marker(
        location=gps_coordinates,
        popup="화재 발생 지점",
        icon=folium.Icon(icon="fire", color="red")
    ).add_to(m)

    # Fire spread prediction circles
    colors = ["red", "orange", "yellow"]
    for idx, prediction in enumerate(predictions):
        folium.Circle(
            location=prediction['coordinates'],
            radius=prediction['radius'],
            color=colors[idx],
            fill=True,
            fill_opacity=0.4,
            popup=f"{idx+1}시간 후 확산 영역"
        ).add_to(m)

    # Facilities
    for _, row in filtered_data.iterrows():
        folium.Marker(
            location=(row['공간위치G'].split()[1], row['공간위치G'].split()[0]),
            popup=f"시설: {row['케이블관리번호']}"
        ).add_to(m)

    folium_static(m)

# Main app
def main():
    st.title("🔥 화재 영향권 시설 조회")

    address = st.text_input("🏠 화재 발생 주소를 입력하세요:")
    fire_time = st.time_input("⏰ 화재 발생 시간을 입력하세요:")

    if st.button("화재 확산 예측 및 시설 조회"):
        gps_coordinates = get_gps_from_address(address)
        if gps_coordinates:
            st.success(f"📍 GPS 좌표: {gps_coordinates}")
            weather_info = get_weather_info(gps_coordinates[0], gps_coordinates[1])
            try:
                predictions = get_fire_spread_prediction(gps_coordinates, weather_info, fire_time)

                # Load facility data
                file_path = 'AI교육_케이블현황_GIS_경남 양산,SKT_샘플2.csv'
                data = pd.read_csv(file_path)

                # Filter facilities and display results
                for idx, (key, prediction) in enumerate(predictions.items()):
                    radius = prediction['radius']
                    filtered_data = filter_facilities(data, gps_coordinates, radius)
                    st.write(f"{key} 확산 영역 내 시설")
                    st.dataframe(filtered_data)

                # Display map
                display_fire_map(gps_coordinates, list(predictions.values()), filtered_data)
            except Exception as e:
                st.error(f"예측 요청 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()
