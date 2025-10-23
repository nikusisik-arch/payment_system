import streamlit as st
import pandas as pd
import json
import requests
import base64
from datetime import datetime
import io

# Настройка страницы
st.set_page_config(
    page_title="Payment System",
    page_icon="💰",
    layout="wide"
)

# Получаем настройки из secrets
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO_OWNER = st.secrets["REPO_OWNER"] 
    REPO_NAME = st.secrets["REPO_NAME"]
    FILE_PATH = "data/payments.json"
except KeyError as e:
    st.error(f"❌ Ошибка конфигурации: {e}. Проверьте файл secrets.toml")
    st.stop()

# Функции для работы с GitHub
def get_file_from_github():
    """Загружает файл с данными из GitHub"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            content = response.json()
            file_content = base64.b64decode(content['content']).decode('utf-8')
            data = json.loads(file_content)
            return data, content['sha']
        else:
            return [], None
    except Exception as e:
        st.error(f"Ошибка загрузки данных: {e}")
        return [], None

def save_file_to_github(data, sha=None):
    """Сохраняет файл с данными в GitHub"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    content = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    ).decode('utf-8')
    
    payload = {
        "message": f"Update payments data - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "content": content
    }
    
    if sha:
        payload["sha"] = sha
    
    try:
        response = requests.put(url, headers=headers, json=payload)
        return response.status_code in [200, 201]
    except Exception as e:
        st.error(f"Ошибка сохранения данных: {e}")
        return False

# Функции для работы с данными
def load_paid_visits():
    """Загружает оплаченные визиты из GitHub"""
    with st.spinner("Загружаем данные из GitHub..."):
        data, sha = get_file_from_github()
        if data:
            df = pd.DataFrame(data)
            st.session_state['github_sha'] = sha
            return df
        else:
            st.session_state['github_sha'] = None
            return pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date', 'payment_date', 'payment_amount'])

def save_paid_visits(visits_df):
    """Сохраняет оплаченные визиты в GitHub"""
    with st.spinner("Сохраняем данные в GitHub..."):
        # Загружаем существующие данные
        existing_data, current_sha = get_file_from_github()
        
        # Добавляем новые данные
        new_data = visits_df.to_dict('records')
        all_data = existing_data + new_data
        
        # Сохраняем в GitHub
        success = save_file_to_github(all_data, current_sha)
        
        if success:
            st.success("✅ Данные успешно сохранены в GitHub!")
            # Обновляем локальный кэш
            st.session_state['github_sha'] = None
        else:
            st.error("❌ Ошибка сохранения в GitHub")
        
        return success

def clear_all_data():
    """Очищает все данные в GitHub"""
    with st.spinner("Очищаем данные в GitHub..."):
        existing_data, current_sha = get_file_from_github()
        success = save_file_to_github([], current_sha)
        
        if success:
            st.success("✅ Все данные очищены!")
            st.session_state['github_sha'] = None
        else:
            st.error("❌ Ошибка очистки данных")
        
        return success

# Обработка данных визитов
def process_visits(uploaded_df):
    """Обрабатывает загруженные визиты и находит дубликаты"""
    # Переименовываем столбцы для удобства
    uploaded_df.columns = ['subject_id', 'visit_name', 'visit_date']
    
    # Преобразуем даты
    uploaded_df['visit_date'] = pd.to_datetime(uploaded_df['visit_date']).dt.strftime('%Y-%m-%d')
    
    # Загружаем уже оплаченные визиты
    paid_visits = load_paid_visits()
    
    if not paid_visits.empty:
        # Создаем ключи для сравнения
        uploaded_df['full_key'] = uploaded_df['subject_id'].astype(str) + '_' + uploaded_df['visit_name'].astype(str) + '_' + uploaded_df['visit_date'].astype(str)
        paid_visits['full_key'] = paid_visits['subject_id'].astype(str) + '_' + paid_visits['visit_name'].astype(str) + '_' + paid_visits['visit_date'].astype(str)
        
        uploaded_df['visit_type_key'] = uploaded_df['subject_id'].astype(str) + '_' + uploaded_df['visit_name'].astype(str)
        paid_visits['visit_type_key'] = paid_visits['subject_id'].astype(str) + '_' + paid_visits['visit_name'].astype(str)
        
        uploaded_df['date_key'] = uploaded_df['subject_id'].astype(str) + '_' + uploaded_df['visit_date'].astype(str)
        paid_visits['date_key'] = paid_visits['subject_id'].astype(str) + '_' + paid_visits['visit_date'].astype(str)
        
        # Находим различные типы совпадений
        exact_duplicates_mask = uploaded_df['full_key'].isin(paid_visits['full_key'])
        same_visit_type_mask = (uploaded_df['visit_type_key'].isin(paid_visits['visit_type_key'])) & (~exact_duplicates_mask)
        same_date_mask = (uploaded_df['date_key'].isin(paid_visits['date_key'])) & (~exact_duplicates_mask) & (~same_visit_type_mask)
        
        # Разделяем данные на категории
        new_visits = uploaded_df[~exact_duplicates_mask & ~same_visit_type_mask & ~same_date_mask].copy()
        exact_duplicates = uploaded_df[exact_duplicates_mask].copy()
        same_visit_different_date = uploaded_df[same_visit_type_mask].copy()
        suspicious_same_date = uploaded_df[same_date_mask].copy()
        
        # Добавляем информацию о предыдущих записях
        if not exact_duplicates.empty:
            exact_duplicates = exact_duplicates.merge(
                paid_visits[['full_key', 'payment_date']].rename(columns={'payment_date': 'previous_payment_date'}),
                on='full_key', how='left'
            )
        
        if not same_visit_different_date.empty:
            same_visit_different_date = same_visit_different_date.merge(
                paid_visits[['visit_type_key', 'visit_date', 'payment_date']].rename(columns={
                    'visit_date': 'previous_visit_date', 'payment_date': 'previous_payment_date'
                }),
                on='visit_type_key', how='left'
            )
        
        if not suspicious_same_date.empty:
            suspicious_same_date = suspicious_same_date.merge(
                paid_visits[['date_key', 'visit_name', 'payment_date']].rename(columns={
                    'visit_name': 'previous_visit_name', 'payment_date': 'previous_payment_date'
                }),
                on='date_key', how='left'
            )
        
        # Убираем служебные столбцы
        columns_to_drop = ['full_key', 'visit_type_key', 'date_key']
        for df in [new_visits, exact_duplicates, same_visit_different_date, suspicious_same_date]:
            if not df.empty:
                df.drop(columns_to_drop, axis=1, inplace=True)
        
    else:
        new_visits = uploaded_df.copy()
        exact_duplicates = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
        same_visit_different_date = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
        suspicious_same_date = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
    
    return new_visits, exact_duplicates, same_visit_different_date, suspicious_same_date, paid_visits

# Основное приложение
def main():
    def main():
        import streamlit as st
import pandas as pd
import json
import requests
import base64
from datetime import datetime
import io

# Настройка страницы
st.set_page_config(
    page_title="Payment System",
    page_icon="💰",
    layout="wide"
)

# Получаем настройки из secrets
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO_OWNER = st.secrets["REPO_OWNER"] 
    REPO_NAME = st.secrets["REPO_NAME"]
    FILE_PATH = "data/payments.json"
except KeyError as e:
    st.error(f"❌ Ошибка конфигурации: {e}. Проверьте файл secrets.toml")
    st.stop()

# Функции для работы с GitHub
def get_file_from_github():
    """Загружает файл с данными из GitHub"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            content = response.json()
            file_content = base64.b64decode(content['content']).decode('utf-8')
            data = json.loads(file_content)
            return data, content['sha']
        else:
            return [], None
    except Exception as e:
        st.error(f"Ошибка загрузки данных: {e}")
        return [], None

def save_file_to_github(data, sha=None):
    """Сохраняет файл с данными в GitHub"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    content = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    ).decode('utf-8')
    
    payload = {
        "message": f"Update payments data - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "content": content
    }
    
    if sha:
        payload["sha"] = sha
    
    try:
        response = requests.put(url, headers=headers, json=payload)
        return response.status_code in [200, 201]
    except Exception as e:
        st.error(f"Ошибка сохранения данных: {e}")
        return False

# Функции для работы с данными
def load_paid_visits():
    """Загружает оплаченные визиты из GitHub"""
    with st.spinner("Загружаем данные из GitHub..."):
        data, sha = get_file_from_github()
        if data:
            df = pd.DataFrame(data)
            st.session_state['github_sha'] = sha
            return df
        else:
            st.session_state['github_sha'] = None
            return pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date', 'payment_date', 'payment_amount'])

def save_paid_visits(visits_df):
    """Сохраняет оплаченные визиты в GitHub"""
    with st.spinner("Сохраняем данные в GitHub..."):
        # Загружаем существующие данные
        existing_data, current_sha = get_file_from_github()
        
        # Добавляем новые данные
        new_data = visits_df.to_dict('records')
        all_data = existing_data + new_data
        
        # Сохраняем в GitHub
        success = save_file_to_github(all_data, current_sha)
        
        if success:
            st.success("✅ Данные успешно сохранены в GitHub!")
            # Обновляем локальный кэш
            st.session_state['github_sha'] = None
        else:
            st.error("❌ Ошибка сохранения в GitHub")
        
        return success

def clear_all_data():
    """Очищает все данные в GitHub"""
    with st.spinner("Очищаем данные в GitHub..."):
        existing_data, current_sha = get_file_from_github()
        success = save_file_to_github([], current_sha)
        
        if success:
            st.success("✅ Все данные очищены!")
            st.session_state['github_sha'] = None
        else:
            st.error("❌ Ошибка очистки данных")
        
        return success

# Обработка данных визитов
def process_visits(uploaded_df):
    """Обрабатывает загруженные визиты и находит дубликаты"""
    # Переименовываем столбцы для удобства
    uploaded_df.columns = ['subject_id', 'visit_name', 'visit_date']
    
    # Преобразуем даты
    uploaded_df['visit_date'] = pd.to_datetime(uploaded_df['visit_date']).dt.strftime('%Y-%m-%d')
    
    # Загружаем уже оплаченные визиты
    paid_visits = load_paid_visits()
    
    if not paid_visits.empty:
        # Создаем ключи для сравнения
        uploaded_df['full_key'] = uploaded_df['subject_id'].astype(str) + '_' + uploaded_df['visit_name'].astype(str) + '_' + uploaded_df['visit_date'].astype(str)
        paid_visits['full_key'] = paid_visits['subject_id'].astype(str) + '_' + paid_visits['visit_name'].astype(str) + '_' + paid_visits['visit_date'].astype(str)
        
        uploaded_df['visit_type_key'] = uploaded_df['subject_id'].astype(str) + '_' + uploaded_df['visit_name'].astype(str)
        paid_visits['visit_type_key'] = paid_visits['subject_id'].astype(str) + '_' + paid_visits['visit_name'].astype(str)
        
        uploaded_df['date_key'] = uploaded_df['subject_id'].astype(str) + '_' + uploaded_df['visit_date'].astype(str)
        paid_visits['date_key'] = paid_visits['subject_id'].astype(str) + '_' + paid_visits['visit_date'].astype(str)
        
        # Находим различные типы совпадений
        exact_duplicates_mask = uploaded_df['full_key'].isin(paid_visits['full_key'])
        same_visit_type_mask = (uploaded_df['visit_type_key'].isin(paid_visits['visit_type_key'])) & (~exact_duplicates_mask)
        same_date_mask = (uploaded_df['date_key'].isin(paid_visits['date_key'])) & (~exact_duplicates_mask) & (~same_visit_type_mask)
        
        # Разделяем данные на категории
        new_visits = uploaded_df[~exact_duplicates_mask & ~same_visit_type_mask & ~same_date_mask].copy()
        exact_duplicates = uploaded_df[exact_duplicates_mask].copy()
        same_visit_different_date = uploaded_df[same_visit_type_mask].copy()
        suspicious_same_date = uploaded_df[same_date_mask].copy()
        
        # Добавляем информацию о предыдущих записях
        if not exact_duplicates.empty:
            exact_duplicates = exact_duplicates.merge(
                paid_visits[['full_key', 'payment_date']].rename(columns={'payment_date': 'previous_payment_date'}),
                on='full_key', how='left'
            )
        
        if not same_visit_different_date.empty:
            same_visit_different_date = same_visit_different_date.merge(
                paid_visits[['visit_type_key', 'visit_date', 'payment_date']].rename(columns={
                    'visit_date': 'previous_visit_date', 'payment_date': 'previous_payment_date'
                }),
                on='visit_type_key', how='left'
            )
        
        if not suspicious_same_date.empty:
            suspicious_same_date = suspicious_same_date.merge(
                paid_visits[['date_key', 'visit_name', 'payment_date']].rename(columns={
                    'visit_name': 'previous_visit_name', 'payment_date': 'previous_payment_date'
                }),
                on='date_key', how='left'
            )
        
        # Убираем служебные столбцы
        columns_to_drop = ['full_key', 'visit_type_key', 'date_key']
        for df in [new_visits, exact_duplicates, same_visit_different_date, suspicious_same_date]:
            if not df.empty:
                df.drop(columns_to_drop, axis=1, inplace=True)
        
    else:
        new_visits = uploaded_df.copy()
        exact_duplicates = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
        same_visit_different_date = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
        suspicious_same_date = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
    
    return new_visits, exact_duplicates, same_visit_different_date, suspicious_same_date, paid_visits

# Основное приложение
def main():
    # Диагностический блок
    st.write("🔍 **Диагностика подключения к GitHub:**")
    
    try:
        st.write(f"**REPO_OWNER:** {REPO_OWNER}")
        st.write(f"**REPO_NAME:** {REPO_NAME}")
        st.write(f"**Токен начинается с:** {GITHUB_TOKEN[:10]}...")
        st.write(f"**Длина токена:** {len(GITHUB_TOKEN)}")
        
        # Тестируем подключение к репозиторию
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        response = requests.get(url, headers=headers)
        
        st.write(f"**Статус ответа GitHub API:** {response.status_code}")
        
        if response.status_code == 200:
            st.success("✅ Репозиторий доступен!")
            
            # Проверяем файл data/payments.json
            file_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
            file_response = requests.get(file_url, headers=headers)
            st.write(f"**Статус файла data/payments.json:** {file_response.status_code}")
            
            if file_response.status_code == 200:
                st.success("✅ Файл data/payments.json найден!")
            elif file_response.status_code == 404:
                st.warning("⚠️ Файл data/payments.json не найден! Создайте его.")
                st.info("Создайте файл data/payments.json в репозитории с содержимым: []")
            
        elif response.status_code == 404:
            st.error("❌ Репозиторий не найден! Проверьте REPO_OWNER и REPO_NAME")
        elif response.status_code == 401:
            st.error("❌ Неверный токен! Проверьте GITHUB_TOKEN")
        else:
            st.error(f"❌ Ошибка: {response.status_code}")
            if response.text:
                st.code(response.text)
                
    except Exception as e:
        st.error(f"❌ Ошибка диагностики: {e}")
    
    st.markdown("---")
    
    # Минималистичный CSS
    st.markdown("""
    <style>
    .app-header {
        display: flex;
        align-items: center;
        padding: 1rem 0 2rem 0;
        border-bottom: 1px solid #e6e9ef;
        margin-bottom: 2rem;
    }
    .app-logo {
        display: flex;
        align-items: center;
        margin-right: auto;
    }
    .logo-icon {
        width: 40px;
        height: 40px;
        background: #1f77b4;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.5rem;
        margin-right: 1rem;
        color: white;
    }
    .app-title {
        font-size: 1.8rem;
        font-weight: 600;
        color: #1f77b4;
        margin: 0;
    }
    .app-version {
        background: #f8f9fa;
        color: #6c757d;
        padding: 0.2rem 0.6rem;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 500;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Простой заголовок
    st.markdown("""
    <div class="app-header">
        <div class="app-logo">
            <div class="logo-icon">💰</div>
            <div class="app-title">Payment System</div>
        </div>
        <div class="app-version">v2.0 GitHub</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("### 🔗 Данные сохраняются в GitHub (надежное хранение)")
    st.markdown("---")
    
    # Диагностический блок
    st.write("🔍 **Диагностика подключения к GitHub:**")
    
    try:
        st.write(f"**REPO_OWNER:** {REPO_OWNER}")
        st.write(f"**REPO_NAME:** {REPO_NAME}")
        st.write(f"**Токен начинается с:** {GITHUB_TOKEN[:10]}...")
        st.write(f"**Длина токена:** {len(GITHUB_TOKEN)}")
        
        # Тестируем подключение
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        response = requests.get(url, headers=headers)
        
        st.write(f"**Статус ответа GitHub API:** {response.status_code}")
        
        if response.status_code == 200:
            st.success("✅ Репозиторий доступен!")
        elif response.status_code == 404:
            st.error("❌ Репозиторий не найден! Проверьте REPO_OWNER и REPO_NAME")
        elif response.status_code == 401:
            st.error("❌ Неверный токен! Проверьте GITHUB_TOKEN")
        else:
            st.error(f"❌ Ошибка: {response.status_code} - {response.text}")
            
    except Exception as e:
        st.error(f"❌ Ошибка диагностики: {e}")
    
    st.markdown("---")
    
    # Минималистичный CSS
    st.markdown("""
    <style>
    .app-header {
        display: flex;
        align-items: center;
        padding: 1rem 0 2rem 0;
        border-bottom: 1px solid #e6e9ef;
        margin-bottom: 2rem;
    }
    .app-logo {
        display: flex;
        align-items: center;
        margin-right: auto;
    }
    .logo-icon {
        width: 40px;
        height: 40px;
        background: #1f77b4;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.5rem;
        margin-right: 1rem;
        color: white;
    }
    .app-title {
        font-size: 1.8rem;
        font-weight: 600;
        color: #1f77b4;
        margin: 0;
    }
    .app-version {
        background: #f8f9fa;
        color: #6c757d;
        padding: 0.2rem 0.6rem;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 500;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Простой заголовок
    st.markdown("""
    <div class="app-header">
        <div class="app-logo">
            <div class="logo-icon">💰</div>
            <div class="app-title">Payment System</div>
        </div>
        <div class="app-version">v2.0 GitHub</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("### 🔗 Данные сохраняются в GitHub (надежное хранение)")
    st.markdown("---")
    
    # Проверяем подключение к GitHub
    with st.sidebar:
        st.header("🔧 Статус системы")
        
        # Проверяем подключение
        try:
            data, sha = get_file_from_github()
            st.success("✅ GitHub подключен")
            st.info(f"📊 Записей в базе: {len(data)}")
        except:
            st.error("❌ Ошибка подключения к GitHub")
        
        st.markdown("---")
        
        st.header("📋 Инструкция")
        st.markdown("""
        **Формат Excel-файла:**
        - Столбец A: ID субъекта
        - Столбец B: Название визита  
        - Столбец C: Дата визита
        
        **🔍 Проверка дубликатов:**
        - **Точные дубликаты**: ID + визит + дата
        - **Тот же тип визита**: ID + визит (другая дата)
        - **Подозрительные**: ID + дата (другой визит)
        """)
    
    # Основная область
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.header("📁 Загрузка данных")
        uploaded_file = st.file_uploader(
            "Выберите Excel-файл с данными визитов",
            type=['xlsx', 'xls'],
            help="Файл должен содержать: ID субъекта, Название визита, Дата визита"
        )
        
        if uploaded_file is not None:
            try:
                # Загружаем данные
                df = pd.read_excel(uploaded_file)
                
                st.success(f"✅ Файл загружен успешно! Найдено {len(df)} записей")
                
                # Показываем превью данных
                st.subheader("👀 Превью загруженных данных")
                st.dataframe(df.head(10), use_container_width=True)
                
                # Обрабатываем данные
                new_visits, exact_duplicates, same_visit_different_date, suspicious_same_date, paid_visits = process_visits(df.copy())
                
                st.markdown("---")
                
                # Результаты обработки
                tab1, tab2, tab3, tab4, tab5 = st.tabs([
                    f"🆕 Новые визиты ({len(new_visits)})", 
                    f"⚠️ Точные дубликаты ({len(exact_duplicates)})",
                    f"🔄 Тот же тип визита ({len(same_visit_different_date)})",
                    f"🚨 Подозрительные ({len(suspicious_same_date)})",
                    f"📊 Сводка"
                ])
                
                with tab1:
                    st.subheader("🆕 Новые визиты к оплате")
                    if not new_visits.empty:
                        st.success(f"Найдено {len(new_visits)} новых визитов")
                        st.dataframe(new_visits, use_container_width=True)
                        
                        # Группировка по субъектам
                        summary = new_visits.groupby('subject_id').size().reset_index(name='количество_визитов')
                        st.subheader("📋 Сводка по субъектам")
                        st.dataframe(summary, use_container_width=True)
                        
                    else:
                        st.info("ℹ️ Нет новых визитов для оплаты")
                
                with tab2:
                    st.subheader("⚠️ Точные дубликаты")
                    if not exact_duplicates.empty:
                        st.error(f"🚫 Найдено {len(exact_duplicates)} точных дубликатов!")
                        st.warning("**Эти визиты уже были оплачены с точно такими же данными**")
                        
                        for _, row in exact_duplicates.iterrows():
                            with st.expander(f"🚫 {row['subject_id']} - {row['visit_name']} - {row['visit_date']}"):
                                st.write(f"**ID пациента:** {row['subject_id']}")
                                st.write(f"**Название визита:** {row['visit_name']}")
                                st.write(f"**Дата визита:** {row['visit_date']}")
                                if 'previous_payment_date' in row and pd.notna(row['previous_payment_date']):
                                    st.write(f"**Дата предыдущей оплаты:** {row['previous_payment_date']}")
                                st.error("❌ **ТОЧНЫЙ ДУБЛИКАТ**: Не будет оплачен!")
                        
                    else:
                        st.success("✅ Точных дубликатов не найдено")
                
                with tab3:
                    st.subheader("🔄 Тот же тип визита с другой датой")
                    if not same_visit_different_date.empty:
                        st.warning(f"⚠️ Найдено {len(same_visit_different_date)} визитов того же типа с другими датами")
                        st.info("**Визиты того же типа, но с другими датами. Возможно, дата была исправлена.**")
                        
                        for _, row in same_visit_different_date.iterrows():
                            with st.expander(f"⚠️ {row['subject_id']} - {row['visit_name']} - {row['visit_date']}"):
                                st.write(f"**ID пациента:** {row['subject_id']}")
                                st.write(f"**Название визита:** {row['visit_name']}")
                                st.write(f"**Текущая дата визита:** {row['visit_date']}")
                                if 'previous_visit_date' in row and pd.notna(row['previous_visit_date']):
                                    st.write(f"**Ранее оплаченная дата:** {row['previous_visit_date']}")
                                    st.write(f"**Дата предыдущей оплаты:** {row['previous_payment_date']}")
                                st.warning("🔄 **Дата изменилась**: Проверьте, нужна ли доплата")
                        
                        # Опция добавить в оплату
                        st.markdown("---")
                        add_same_type = st.checkbox("✅ Добавить эти визиты к оплате", 
                                                   help="Отметьте, если визиты с измененными датами тоже нужно оплатить",
                                                   key="add_same_type_checkbox")
                        
                    else:
                        st.success("✅ Визитов того же типа с другими датами не найдено")
                        add_same_type = False
                
                with tab4:
                    st.subheader("🚨 Подозрительные визиты (одна дата, разные названия)")
                    if not suspicious_same_date.empty:
                        st.error(f"🚨 Найдено {len(suspicious_same_date)} подозрительных визитов!")
                        st.warning("**У одного пациента в один день записаны разные визиты. Возможно, ошибка в данных.**")
                        
                        for _, row in suspicious_same_date.iterrows():
                            with st.expander(f"🚨 {row['subject_id']} - {row['visit_name']} - {row['visit_date']}"):
                                st.write(f"**ID пациента:** {row['subject_id']}")
                                st.write(f"**Текущий визит:** {row['visit_name']}")
                                st.write(f"**Дата:** {row['visit_date']}")
                                if 'previous_visit_name' in row and pd.notna(row['previous_visit_name']):
                                    st.write(f"**Ранее оплаченный визит в эту дату:** {row['previous_visit_name']}")
                                    st.write(f"**Дата предыдущей оплаты:** {row['previous_payment_date']}")
                                st.error("🚨 **ПОДОЗРИТЕЛЬНО**: Два разных визита в один день!")
                                st.info("💡 **Рекомендация**: Проверьте в ИРК, какой визит правильный")
                        
                        # Опция добавить в оплату
                        st.markdown("---")
                        add_suspicious = st.checkbox("⚠️ Все равно добавить к оплате", 
                                                    help="Отметьте только если уверены, что данные корректны",
                                                    key="add_suspicious_checkbox")
                        
                    else:
                        st.success("✅ Подозрительных визитов не найдено")
                        add_suspicious = False
                
                with tab5:
                    st.subheader("📊 Общая сводка")
                    
                    col_stat1, col_stat2, col_stat3, col_stat4, col_stat5 = st.columns(5)
                    
                    with col_stat1:
                        st.metric("Всего в файле", len(df))
                    
                    with col_stat2:
                        st.metric("Новые к оплате", len(new_visits))
                    
                    with col_stat3:
                        st.metric("Точные дубликаты", len(exact_duplicates))
                    
                    with col_stat4:
                        st.metric("Тот же тип визита", len(same_visit_different_date))
                    
                    with col_stat5:
                        st.metric("Подозрительные", len(suspicious_same_date))
                    
                    # Детальная статистика
                    st.markdown("---")
                    st.subheader("📈 Рекомендации")
                    
                    if len(exact_duplicates) > 0:
                        st.error(f"🚫 **{len(exact_duplicates)} точных дубликатов** - автоматически исключены из оплаты")
                    
                    if len(same_visit_different_date) > 0:
                        st.warning(f"⚠️ **{len(same_visit_different_date)} визитов** с измененными датами - проверьте и решите")
                    
                    if len(suspicious_same_date) > 0:
                        st.error(f"🚨 **{len(suspicious_same_date)} подозрительных визитов** - проверьте в ИРК!")
                    
                    if len(new_visits) > 0:
                        st.success(f"✅ **{len(new_visits)} новых визитов** готовы к оплате")
                
                # Формируем итоговый список для оплаты
                visits_to_pay = new_visits.copy()
                
                if 'add_same_type' in locals() and add_same_type and not same_visit_different_date.empty:
                    visits_to_pay = pd.concat([visits_to_pay, same_visit_different_date[['subject_id', 'visit_name', 'visit_date']]], ignore_index=True)
                
                if 'add_suspicious' in locals() and add_suspicious and not suspicious_same_date.empty:
                    visits_to_pay = pd.concat([visits_to_pay, suspicious_same_date[['subject_id', 'visit_name', 'visit_date']]], ignore_index=True)
                
                # Кнопки действий
                if not visits_to_pay.empty:
                    st.markdown("---")
                    st.subheader("🎯 Действия")
                    
                    col_btn1, col_btn2, col_btn3 = st.columns(3)
                    
                    with col_btn1:
                        # Скачать отчет
                        excel_buffer = io.BytesIO()
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            visits_to_pay.to_excel(writer, sheet_name='К оплате', index=False)
                            
                            if not visits_to_pay.empty:
                                summary = visits_to_pay.groupby('subject_id').size().reset_index(name='количество_визитов')
                                summary.to_excel(writer, sheet_name='Сводка', index=False)
                            
                            if not exact_duplicates.empty:
                                exact_duplicates.to_excel(writer, sheet_name='Точные дубликаты', index=False)
                            
                            if not same_visit_different_date.empty:
                                same_visit_different_date.to_excel(writer, sheet_name='Тот же тип визита', index=False)
                            
                            if not suspicious_same_date.empty:
                                suspicious_same_date.to_excel(writer, sheet_name='Подозрительные', index=False)
                        
                        st.download_button(
                            label="📥 Скачать полный отчет",
                            data=excel_buffer.getvalue(),
                            file_name=f"polnyj_otchet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="download_report_btn"
                        )
                    
                    with col_btn2:
                        if st.button("✅ Отметить как оплаченные", type="primary", key="mark_paid_btn"):
                            # Добавляем информацию об оплате
                            visits_to_save = visits_to_pay.copy()
                            visits_to_save['payment_date'] = datetime.now().strftime('%Y-%m-%d')
                            visits_to_save['payment_amount'] = 0.0
                            
                            # Сохраняем в GitHub
                            success = save_paid_visits(visits_to_save[['subject_id', 'visit_name', 'visit_date', 'payment_date', 'payment_amount']])
                            
                            if success:
                                st.success(f"✅ {len(visits_to_pay)} визитов отмечены как оплаченные!")
                                st.rerun()
                    
                    with col_btn3:
                        if st.button("🔄 Обновить данные", key="refresh_data_btn"):
                            st.rerun()
                
            except Exception as e:
                st.error(f"❌ Ошибка при обработке файла: {str(e)}")
                st.info("Убедитесь, что файл содержит данные в правильном формате")
    
    with col2:
        st.header("📈 История оплат")
        
        # Загружаем и показываем историю
        paid_visits = load_paid_visits()
        
        if not paid_visits.empty:
            # Статистика
            st.subheader("📊 Статистика")
            st.metric("Всего оплаченных визитов", len(paid_visits))
            st.metric("Уникальных субъектов", paid_visits['subject_id'].nunique())
            st.metric("Уникальных типов визитов", paid_visits['visit_name'].nunique())
            
            # Последние оплаты
            st.subheader("🕒 Последние оплаты")
            recent_payments = paid_visits.sort_values('payment_date', ascending=False).head(5)
            for _, payment in recent_payments.iterrows():
                with st.container():
                    st.text(f"📅 {payment['payment_date']}")
                    st.text(f"👤 {payment['subject_id']}")
                    st.text(f"🏥 {payment['visit_name']}")
                    st.text(f"📆 {payment['visit_date']}")
                    st.markdown("---")
        else:
            st.info("История оплат пустая")
        
        # Управление данными
        st.subheader("🛠️ Управление")
        
        if st.button("📊 Показать всю историю", key="show_history_btn"):
            if not paid_visits.empty:
                st.dataframe(paid_visits[['subject_id', 'visit_name', 'visit_date', 'payment_date']], use_container_width=True)
            else:
                st.info("История пустая")
        
        # Экспорт истории
        if not paid_visits.empty:
            excel_buffer = io.BytesIO()
            paid_visits.to_excel(excel_buffer, index=False, engine='openpyxl')
            
            st.download_button(
                label="📥 Экспорт истории в Excel",
                data=excel_buffer.getvalue(),
                file_name=f"istoriya_oplat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="export_history_btn"
            )
        
        # Очистка истории
        if 'confirm_delete' not in st.session_state:
            st.session_state.confirm_delete = False
        
        if not st.session_state.confirm_delete:
            if st.button("🗑️ Очистить всю историю", help="Удалить все записи об оплатах", key="clear_history_btn"):
                st.session_state.confirm_delete = True
                st.rerun()
        else:
            st.warning("⚠️ Вы уверены, что хотите удалить всю историю оплат?")
            
            col_confirm1, col_confirm2 = st.columns(2)
            
            with col_confirm1:
                if st.button("✅ Да, удалить", type="primary", key="confirm_delete_btn"):
                    success = clear_all_data()
                    if success:
                        st.session_state.confirm_delete = False
                        st.rerun()
            
            with col_confirm2:
                if st.button("❌ Отмена", key="cancel_delete_btn"):
                    st.session_state.confirm_delete = False
                    st.rerun()

if __name__ == "__main__":
    main()



