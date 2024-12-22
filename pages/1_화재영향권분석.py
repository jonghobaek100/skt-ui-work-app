import streamlit as st
import pandas as pd
import requests
from geopy.distance import geodesic
import folium
from streamlit_folium import folium_static
from folium import PolyLine
import streamlit.components.v1 as components
import datetime
import pytz  
from dotenv import load_dotenv
import os
from folium.features import RegularPolygonMarker

# openai 라이브러리 대신 openai.py 모듈 형태 사용 예제
from openai import OpenAI

# Load environment variables
load_dotenv()

# Naver Map API keys (retrieve from .env file)
NAVER_CLIENT_ID = os.getenv('NAVER_CLIENT_ID')
NAVER_CLIENT_SECRET = os.getenv('NAVER_CLIENT_SECRET')

# Weather API key
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')

# OpenAI API key
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Ensure keys are loaded correctly
if not all([NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, WEATHER_API_KEY, OPENAI_API_KEY]):
    st.error("API keys are missing. Please check your .env file.")

# OpenAI client 설정
client = OpenAI(api_key=OPENAI_API_KEY)

WEATHER_BASE_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst" #초단기 실황조회

#전역변수 선언
seoul_tz = pytz.timezone('Asia/Seoul')
now = datetime.datetime.now(seoul_tz) - datetime.timedelta(hours=1)  # 현재시간 대비 1시간 전 날씨
base_date = now.strftime("%Y%m%d")
base_time = now.strftime("%H00")  # 정시에 업데이트 되므로 "HH00" 형태로 시간 설정

# Function to get GPS coordinates from Naver API using an address
def get_gps_from_address(address):
    url = "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode"
    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET
    }
    params = {"query": address}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        try:
            result = response.json()
            # result 검사
            if 'meta' in result and 'totalCount' in result['meta'] and result['meta']['totalCount'] > 0:
                if 'addresses' in result and len(result['addresses']) > 0:
                    lat = result['addresses'][0]['y']
                    lon = result['addresses'][0]['x']
                    return float(lat), float(lon)
                else:
                    return None
            else:
                return None
        except Exception as e:
            st.error(f"Error parsing the response: {e}")
            return None
    else:
        st.error("Failed to get GPS coordinates from Naver API")
        return None

# Function to get weather information from the Korea Meteorological Administration (KMA) API
def get_weather_info(latitude, longitude):
    seoul_tz = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(seoul_tz) - datetime.timedelta(hours=1)
    base_date = now.strftime("%Y%m%d")
    base_time = now.strftime("%H00")
    nx, ny = 55, 127  # 예시 좌표

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
        try:
            data = response.json()
            if data.get("response", {}).get("header", {}).get("resultCode") == "00":
                items = data.get("response", {}).get("body", {}).get("items", {}).get("item")
                return items
            else:
                st.error("데이터 조회에 실패했습니다.")
                return None
        except ValueError:
            st.error("응답에서 JSON을 파싱하는 데 실패했습니다. 응답 내용이 올바르지 않을 수 있습니다.")
            return None
    else:
        st.error(f"API 요청에 실패했습니다. 상태 코드: {response.status_code}")
        return None

# Function to calculate distance from target coordinates
def calculate_distance(row, target_coordinates):
    try:
        points_str = row['공간위치G'].replace("LINESTRING (", "").replace(")", "").split(", ")
        points = [tuple(map(float, point.split())) for point in points_str]
        mid_point = points[len(points) // 2]
        mid_point_coordinates = (mid_point[1], mid_point[0])
        return geodesic(target_coordinates, mid_point_coordinates).meters
    except:
        return None

# Function to call OpenAI API to predict future fire areas
def predict_future_fire_areas(weather_data, filtered_data, fire_coordinates):
    weather_info_str = ""
    category_mapping = {
        "T1H": "기온(°C)",
        "RN1": "1시간 강수량(mm)",
        "REH": "습도(%)",
        "VEC": "풍향(°)",
        "WSD": "풍속(m/s)"
    }
    for item in weather_data:
        category = item.get("category")
        obsr_value = item.get("obsrValue")
        if category in category_mapping:
            weather_info_str += f"{category_mapping[category]}: {obsr_value}, "
    weather_info_str = weather_info_str.strip().rstrip(',')

    # 여기서 csv에서 필요한 컬럼만 GPT 입력에 활용
    cable_info_str = ""
    for i, row in filtered_data.iterrows():
        cable_info_str += (
            f"시도명:{row['시도명']}, "
            f"시군구명:{row['시군구명']}, "
            f"읍면동명:{row['읍면동명']}, "
            f"리명:{row['리명']}, "
            f"케이블매설위치코드명:{row['케이블매설위치코드명']}, "
            f"케이블코어수:{row['케이블코어수']}, "
            f"접속코어수:{row['접속코어수']}, "
            f"사용코어수:{row['사용코어수']}, "
            f"케이블용도코드명:{row['케이블용도코드명']}, "
            f"준공거리M:{row['준공거리M']}, "
            f"지도거리M:{row['지도거리M']}, "
            f"공간위치G:{row['공간위치G']} | "
        )
    cable_info_str = cable_info_str.strip().rstrip('|')

    # 화재 발생 지점 좌표를 추가 정보로 포함
    fire_coord_str = f"화재 발생 지점 GPS 좌표: {fire_coordinates[0]}, {fire_coordinates[1]}"

    system_instruction = (
        "너는 소방/재난 대응 전문가의 역량을 가진 어시스턴트임. "
        "다음 날씨 정보와 현재 화재 영향 케이블 목록, 그리고 화재 발생 지점 GPS 좌표를 토대로 1시간 후 화재가 확산될 가능성이 높은 지역을 추론하라. "
        "결과는 가능한 해당 CSV 데이터 상에 존재하는 지역(시군구명, 읍면동명)으로 특정해줘. "
        "가능성 있는 후보 지역들을 2~3개 정도 나열해줘."
    )

    user_prompt = f"현재 날씨 정보: {weather_info_str}\n화재 영향 케이블 목록: {cable_info_str}\n{fire_coord_str}\n" \
                  "위 정보를 토대로 1시간 후 화재가 확산될 가능성이 있는 지역(시군구명, 읍면동명)을 CSV 상에서 찾아 2~3개 제시해줘."

    model = "gpt-4o"
    temperature = 0.7
    max_tokens = 1000

    messages_with_metadata = client.chat.completions.create(
        model=model,
        messages=[
          {"role": "system", "content": system_instruction},
          {"role": "user", "content": user_prompt}
        ],
        temperature=temperature,
        max_tokens=max_tokens
    )

    result = messages_with_metadata.choices[0].message.content.strip()
    predicted_areas = [area.strip() for area in result.replace('\n','').split(',') if area.strip()]
    return predicted_areas

def display_predicted_fire_areas(m, predicted_areas):
    for area in predicted_areas:
        coords = get_gps_from_address("경남 양산시 " + area)  
        if coords:
            RegularPolygonMarker(
                location=coords,
                number_of_sides=5,
                radius=10,
                fill_color='green',
                color='green',
                popup=f"예측 화재 확산지역: {area}"
            ).add_to(m)
        else:
            st.warning(f"'{area}' 지역에 대한 좌표를 가져올 수 없습니다.")

# Main Streamlit app
st.title("🔥 화재 영향권 케이블 조회 🗺️")

st.text_area("", """    ○ 화재 발생 지점 인근의 케이블을 조회하는 프로그램v3.2입니다.
    ○ 양산지역만 샘플로 구현된 버전입니다.
    ○ 지도표시 케이블(파란색: 영향 범위 내, 검은색 : 영향 범위 외, 빨간색: 중요케이블)                 
""")

# Custom CSS for rounded edges and section styling
st.markdown(
    """
    <style>
    .section {
        background-color: #f9f9f9;
        padding: 20px;
        margin-bottom: 20px;
        border-radius: 15px;
    }
    .rounded-input {
        border-radius: 15px;
        border: 1px solid #ccc;
        padding: 10px;
        width: 100%;
    }
    .button-style {
        border-radius: 12px;
        background-color: #4CAF50;
        color: white;
        padding: 10px 20px;
        text-align: center;
        font-size: 16px;
        margin: 10px 2px;
        cursor: pointer;
    }
    .result-section {
        background-color: #f0f0f0;
        padding: 20px;
        border-radius: 15px;
        margin-top: 20px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

def address_and_distance_input():
    with st.container():
        address = st.text_input("🏠화재발생 주소를 입력하세요 :", "경남 양산시 중뫼길 36", key='address_input', help="주소를 입력하고 GPS 좌표를 조회하세요.")
        distance_limit_str = st.text_input('📏화재영향 거리를 입력하세요 :', '1000', key='distance_input')

        if st.button("화재발생지점 조회 🛰️", key='gps_button', help="입력된 주소의 GPS 좌표를 조회합니다."):
            gps_coordinates = get_gps_from_address(address)
            if gps_coordinates:
                st.session_state['gps_coordinates'] = gps_coordinates
                st.success(f"📍 GPS 좌표 (네이버맵): {gps_coordinates[0]}, {gps_coordinates[1]}")
                weather_data = get_weather_info(gps_coordinates[0], gps_coordinates[1])
                if weather_data:
                    display_weather_info(weather_data, gps_coordinates)
                else:
                    st.error("날씨 정보를 가져올 수 없습니다.")

                try:
                    distance_limit = float(distance_limit_str)
                except ValueError:
                    st.error("유효한 숫자를 입력하세요.")
                    distance_limit = None

                if distance_limit is not None and weather_data:
                    filtered_data = query_and_display_cables(gps_coordinates, distance_limit)
                    if filtered_data is not None and not filtered_data.empty:
                        predicted_areas = predict_future_fire_areas(weather_data, filtered_data, gps_coordinates)
                        if predicted_areas:
                            st.markdown('<div class="result-section">🗺️ <b>Map 기반 화재 영향 케이블 조회 (예측 화재 확산지역 표시)</b></div>', unsafe_allow_html=True)
                            m = create_cable_map(gps_coordinates, filtered_data)
                            display_predicted_fire_areas(m, predicted_areas)
                            folium_static(m)
                        else:
                            st.write("예측 화재 확산지역 정보를 가져올 수 없습니다.")
            else:
                st.error("GPS 좌표를 가져올 수 없습니다.")

def display_weather_info(weather_data, gps_coordinates):
    st.markdown('<div class="result-section">🌤️ <b>날씨 정보 (기상청 초단기 실황) </b></div>', unsafe_allow_html=True)
    st.write ("                    ※ 기준시간 : ", base_date, base_time, gps_coordinates)
    category_mapping = {
        "T1H": "기온 (°C)",
        "RN1": "1시간 강수량 (mm)",
        "REH": "습도 (%)",
        "VEC": "풍향 (°)",
        "WSD": "풍속 (m/s)"
    }
    selected_categories = ["T1H", "REH", "RN1", "VEC", "WSD"]
    for item in weather_data:
        category = item.get("category")
        if category in selected_categories:
            obsr_value = item.get("obsrValue")
            category_name = category_mapping.get(category, category)
            st.write("  - ", f"{category_name}: {obsr_value}")

def query_and_display_cables(gps_coordinates, distance_limit):
    file_path = './AI교육_케이블현황_GIS_경남 양산,SKT_샘플2.csv'
    data = pd.read_csv(file_path)
    data['계산거리'] = data.apply(lambda row: calculate_distance(row, gps_coordinates), axis=1)
    filtered_data = data[data['계산거리'] <= distance_limit]
    if not filtered_data.empty:
        filtered_data = filtered_data.sort_values(by='계산거리')
        filtered_data.insert(0, '순번', range(1, len(filtered_data) + 1))
        st.markdown('<div class="result-section">📋 <b>화재 영향 케이블 목록</b></div>', unsafe_allow_html=True)
        result = filtered_data[['순번', '계산거리', '케이블관리번호', '시군구명', '읍면동명', '케이블코어수', '사용코어수', '중계기회선수', '중요선로' ]]
        st.dataframe(result)
        st.markdown('<div class="result-section">🗺️ <b>Map 기반 화재 영향 케이블 조회</b></div>', unsafe_allow_html=True)
        m = create_cable_map(gps_coordinates, filtered_data, data)
        folium_static(m)
        return filtered_data
    else:
        st.write(f"{distance_limit}m 내에 케이블이 없습니다.")
        return None

def create_cable_map(gps_coordinates, filtered_data, data=None):
    if data is None:
        file_path = './AI교육_케이블현황_GIS_경남 양산,SKT_샘플2.csv'
        data = pd.read_csv(file_path)
        data['계산거리'] = data.apply(lambda row: calculate_distance(row, gps_coordinates), axis=1)

    map_center = gps_coordinates
    m = folium.Map(location=map_center, zoom_start=14)

    folium.Marker(
        location=gps_coordinates,
        popup="화재 발생 지점",
        icon=folium.Icon(icon='fire', color='red')
    ).add_to(m)

    for _, row in data.iterrows():
        points_str = row['공간위치G'].replace("LINESTRING (", "").replace(")", "").split(", ")
        points = [tuple(map(float, point.split())) for point in points_str]
        line_coordinates = [(point[1], point[0]) for point in points]
        folium.PolyLine(line_coordinates, color="black", weight=2).add_to(m)

    closest_cable = None
    min_distance = float('inf')
    for _, row in filtered_data.iterrows():
        points_str = row['공간위치G'].replace("LINESTRING (", "").replace(")", "").split(", ")
        points = [tuple(map(float, point.split())) for point in points_str]
        line_coordinates = [(point[1], point[0]) for point in points]
        color = 'red' if row['중요선로'] == 'O' else 'blue'
        folium.PolyLine(line_coordinates, color=color, weight=2.5, popup=f"케이블관리번호: {row['케이블관리번호']}").add_to(m)

        folium.CircleMarker(
            location=(line_coordinates[0][0], line_coordinates[0][1]),
            radius=2.5 * 0.55,
            color=color,
            fill=True,
            fill_color=color
        ).add_to(m)
        folium.CircleMarker(
            location=(line_coordinates[-1][0], line_coordinates[-1][1]),
            radius=2.5 * 0.55,
            color=color,
            fill=True,
            fill_color=color
        ).add_to(m)

        if row['계산거리'] < min_distance:
            min_distance = row['계산거리']
            closest_cable = line_coordinates

    if closest_cable:
        closest_point = closest_cable[len(closest_cable) // 2]
        folium.PolyLine([gps_coordinates, closest_point], color='red', weight=2, dash_array='5, 10').add_to(m)
        folium.Marker(
            location=((gps_coordinates[0] + closest_point[0]) / 2, (gps_coordinates[1] + closest_point[1]) / 2),
            icon=folium.DivIcon(html=f'<div style="font-size: 12pt; color: red; white-space: nowrap;">거리: {min_distance:.2f}m</div>')
        ).add_to(m)

    return m

address_and_distance_input()
