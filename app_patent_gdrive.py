import streamlit as st
import os
import io
import json
import re
import google.generativeai as genai
from google.api_core import exceptions

# [추가] Google Drive API 사용을 위한 라이브러리
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- 1. 애플리케이션 기본 설정 ---
st.set_page_config(
    page_title=Google Drive 특허 분석 Q&A (Gemini 2.5),
    page_icon=🚗,
    layout=wide
)

st.title(🧠 지능형 AI 특허 분석 Q&A (Google Drive 연동))
st.markdown(Google Drive에 저장된 특허 자료실을 기반으로, 최신 Gemini 모델이 직접 검색하고 답변합니다.)

# --- 2. 사이드바 - 설정 ---
with st.sidebar
    st.header(✨ AI & Drive 설정)
    # Gemini API 키 입력
    gemini_api_key = st.text_input(Gemini API Key, type=password, help=[Google AI Studio](httpsaistudio.google.comappapikey)에서 발급받으세요.)
    # Google Drive 폴더 ID 입력
    drive_folder_id = st.text_input(Google Drive 폴더 ID, help=특허 PDF가 있는 폴더의 URL 마지막 부분을 입력하세요.)
    # [중요] Google Cloud 서비스 계정 키 입력
    gcp_service_account_json = st.text_area(Google Cloud 서비스 계정 JSON, type=password, help=Google Cloud에서 발급받은 서비스 계정의 JSON 키 내용을 붙여넣으세요.)
    
    st.markdown(---)
    st.header(🤖 모델 선택)
    # [수정] 최신 2.5 모델을 사용하도록 옵션 변경
    selected_model = st.radio(
        답변 생성 모델 선택,
        (gemini-2.5-pro, gemini-2.5-flash),
        captions=[최고 품질 (2.5 Pro), 최신균형 (2.5 Flash)],
        horizontal=True
    )

    if st.button(대화 기록 초기화)
        st.session_state.messages = []
        st.rerun()

# --- 3. 핵심 기능 함수 ---

# [개선] Google Drive 인증 및 서비스 객체 생성 (캐시 사용)
@st.cache_resource
def get_gdrive_service(_credentials_json_str)
    서비스 계정 정보를 사용하여 Google Drive 서비스 객체를 생성합니다.
    try
        creds_dict = json.loads(_credentials_json_str)
        creds = Credentials.from_service_account_info(creds_dict, scopes=['httpswww.googleapis.comauthdrive.readonly'])
        service = build('drive', 'v3', credentials=creds)
        print(✅ Google Drive 인증 성공)
        return service
    except Exception as e
        st.error(fGoogle Drive 인증에 실패했습니다 {e})
        return None

# [개선] Google Drive에서 파일 목록 가져오기 (캐시 사용)
@st.cache_data(ttl=3600)
def list_drive_files(_service, folder_id)
    지정된 Google Drive 폴더 ID에서 모든 PDF 파일 목록을 가져옵니다.
    if not _service
        return []
    print(Google Drive에서 파일 목록을 가져오는 중...)
    try
        query = f'{folder_id}' in parents and mimeType='applicationpdf'
        results = _service.files().list(q=query, pageSize=1000, fields=nextPageToken, files(id, name)).execute()
        items = results.get('files', [])
        return items
    except Exception as e
        st.error(fGoogle Drive에서 파일 목록을 가져오는 데 실패했습니다 {e})
        return []

# 특허 번호를 감지하는 정규 표현식
PATENT_NUMBER_REGEX = re.compile(r'b((USKRCNJPEP)s[d]+([s.][A-Z]d))b', re.IGNORECASE)

# --- 4. 메인 Q&A 로직 (Google Drive 연동) ---

if not all([gemini_api_key, drive_folder_id, gcp_service_account_json])
    st.info(사이드바에 모든 설정 값을 입력해주세요.)
else
    try
        # Google 서비스 인증
        drive_service = get_gdrive_service(gcp_service_account_json)
        genai.configure(api_key=gemini_api_key)
        
        if drive_service
            # 파일 목록 가져오기
            drive_files = list_drive_files(drive_service, drive_folder_id)

            if not drive_files
                st.warning(Google Drive 폴더에서 PDF 파일을 찾을 수 없습니다. 폴더 ID와 공유 설정을 확인해주세요.)
            else
                model = genai.GenerativeModel(model_name=selected_model)

                if messages not in st.session_state
                    st.session_state.messages = []

                for message in st.session_state.messages
                    with st.chat_message(message[role])
                        st.markdown(message[content])

                if prompt = st.chat_input(특허 번호 또는 주제를 질문해보세요...)
                    st.session_state.messages.append({role user, content prompt})
                    with st.chat_message(user)
                        st.markdown(prompt)

                    with st.chat_message(assistant)
                        patent_match = PATENT_NUMBER_REGEX.search(prompt)
                        
                        # --- 모드 1 특정 특허 번호 요약 ---
                        if patent_match
                            patent_number_query = re.sub(r'[s.]', '', patent_match.group(1)).lower()
                            st.info(f정규화된 검색어 '{patent_number_query}'로 Drive에서 특허를 찾고 있습니다...)
                            
                            target_file_info = None
                            for f in drive_files
                                filename_normalized = re.sub(r'[s.]', '', os.path.splitext(f['name'])[0]).lower()
                                if patent_number_query == filename_normalized
                                    target_file_info = f
                                    break
                            
                            if target_file_info
                                with st.spinner(fDrive에서 '{target_file_info['name']}' 파일을 다운로드 및 분석 중...)
                                    try
                                        # Drive에서 파일 다운로드
                                        request = drive_service.files().get_media(fileId=target_file_info['id'])
                                        file_content = io.BytesIO()
                                        downloader = MediaIoBaseDownload(file_content, request)
                                        done = False
                                        while done is False
                                            status, done = downloader.next_chunk()
                                        
                                        # Gemini File API에 임시 업로드
                                        # PDF이므로 MIME 타입을 명시해주는 것이 좋습니다.
                                        uploaded_file = genai.upload_file(
                                            path=file_content.getvalue(), 
                                            display_name=target_file_info['name'],
                                            mime_type=applicationpdf
                                        )
                                        
                                        # Gemini에 요약 요청
                                        summary_prompt = fPlease provide a detailed summary of the attached patent file '{target_file_info['name']}'
                                        response = model.generate_content([summary_prompt, uploaded_file])
                                        
                                        # 임시 파일 삭제 (비용 및 공간 관리)
                                        genai.delete_file(name=uploaded_file.name)
                                        
                                        st.markdown(response.text)
                                        st.session_state.messages.append({role assistant, content response.text})

                                    except Exception as e
                                        st.error(f요약 중 오류 발생 {e})
                            else
                                st.error(fDrive에서 '{prompt.strip()}'에 해당하는 파일을 찾지 못했습니다.)

                        # --- 모드 2 주제 기반 전체 검색 (이 방식은 비효율적이므로 경고) ---
                        else
                            st.warning(⚠️ 주의 주제 검색은 현재 아키텍처에서 매우 비효율적일 수 있습니다. 특정 특허 번호로 질문하는 것을 권장합니다.)
                            with st.spinner(f전체 특허 자료실에서 '{prompt}' 관련 내용을 검색하고 분석하는 중... (시간이 오래 걸릴 수 있습니다))
                                # 이 부분은 Gemini의 grounding 기능을 활용하는 것으로 대체합니다.
                                # 하지만 이 기능을 사용하려면 먼저 파일들을 File API에 업로드해야 하므로, 
                                # 현재 구조에서는 실시간 검색이 어렵습니다.
                                # 여기서는 개념 증명을 위해 첫 5개 파일만 사용하는 것으로 간소화합니다.
                                st.info(개념 증명을 위해 Drive의 첫 5개 파일만 사용하여 답변을 생성합니다.)
                                temp_files_to_ground = []
                                for f_info in drive_files[5]
                                    # 이 부분은 실제 서비스에서는 비효율적입니다.
                                    # 매번 다운로드 - 업로드 과정을 거치기 때문입니다.
                                    # ... (다운로드 및 업로드 로직) ...
                                    pass # 이 부분은 실제 구현 시 많은 시간이 소요되므로 생략
                                
                                st.error(주제 기반 전체 검색 기능은 현재 아키텍처에서 지원되지 않습니다. 이전에 논의했던 'File API에 파일 미리 업로드' 방식이 이 기능에는 더 적합합니다.)

    except Exception as e
        st.error(f애플리케이션 초기화 중 오류가 발생했습니다 {e})
