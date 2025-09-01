import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import os

# Настройка страницы
st.set_page_config(
    page_title="Система учета оплат визитов",
    page_icon="💰",
    layout="wide"
)

# Инициализация базы данных
def init_database():
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS paid_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id TEXT,
            visit_name TEXT,
            visit_date TEXT,
            payment_date TEXT,
            payment_amount REAL
        )
    ''')
    conn.commit()
    conn.close()

# Загрузка оплаченных визитов
def load_paid_visits():
    conn = sqlite3.connect('payments.db')
    try:
        df = pd.read_sql_query("SELECT * FROM paid_visits", conn)
        return df
    except:
        return pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date', 'payment_date', 'payment_amount'])
    finally:
        conn.close()

# Сохранение оплаченных визитов
def save_paid_visits(visits_df):
    conn = sqlite3.connect('payments.db')
    visits_df.to_sql('paid_visits', conn, if_exists='append', index=False)
    conn.close()

# Обработка данных визитов
def process_visits(uploaded_df):
    # Переименовываем столбцы для удобства
    uploaded_df.columns = ['subject_id', 'visit_name', 'visit_date']
   
    # Преобразуем даты
    uploaded_df['visit_date'] = pd.to_datetime(uploaded_df['visit_date']).dt.strftime('%Y-%m-%d')
   
    # Загружаем уже оплаченные визиты
    paid_visits = load_paid_visits()
   
    if not paid_visits.empty:
        # Создаем ключ для сравнения ТОЛЬКО по ID пациента + название визита
        uploaded_df['comparison_key'] = uploaded_df['subject_id'].astype(str) + '_' + uploaded_df['visit_name'].astype(str)
        paid_visits['comparison_key'] = paid_visits['subject_id'].astype(str) + '_' + paid_visits['visit_name'].astype(str)
       
        # Находим визиты, которые уже были оплачены (по ID + название)
        already_paid_mask = uploaded_df['comparison_key'].isin(paid_visits['comparison_key'])
       
        # Разделяем на новые и уже оплаченные
        new_visits = uploaded_df[~already_paid_mask].copy()
        duplicate_visits = uploaded_df[already_paid_mask].copy()
       
        # Добавляем информацию о предыдущих оплатах к дубликатам
        if not duplicate_visits.empty:
            duplicate_visits = duplicate_visits.merge(
                paid_visits[['comparison_key', 'visit_date', 'payment_date']].rename(columns={
                    'visit_date': 'previous_visit_date',
                    'payment_date': 'previous_payment_date'
                }),
                on='comparison_key',
                how='left'
            )
       
        # Убираем служебные столбцы
        new_visits = new_visits.drop('comparison_key', axis=1) if not new_visits.empty else new_visits
        duplicate_visits = duplicate_visits.drop('comparison_key', axis=1) if not duplicate_visits.empty else duplicate_visits
       
    else:
        new_visits = uploaded_df.copy()
        duplicate_visits = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
   
    return new_visits, duplicate_visits, paid_visits

# Основное приложение
def main():
    init_database()
   
    st.title("💰 Система учета оплат визитов исследователям")
    st.markdown("---")
   
    # Боковая панель с информацией
    with st.sidebar:
        st.header("📋 Инструкция")
        st.markdown("""
        **Формат Excel-файла:**
        - Столбец A: ID субъекта
        - Столбец B: Название визита  
        - Столбец C: Дата визита
       
        **Как использовать:**
        1. Загрузите Excel-файл
        2. Проверьте данные
        3. Сформируйте акт оплаты
        4. Отметьте визиты как оплаченные
       
        **⚠️ Важно:**
        Программа проверяет дубли по
        ID пациента + название визита
        (дата может отличаться)
        """)
       
        st.markdown("---")
       
        # Статистика
        paid_visits = load_paid_visits()
        if not paid_visits.empty:
            st.header("📊 Статистика")
            st.metric("Всего оплаченных визитов", len(paid_visits))
            st.metric("Уникальных субъектов", paid_visits['subject_id'].nunique())
            st.metric("Уникальных типов визитов", paid_visits['visit_name'].nunique())
   
    # Основная область
    col1, col2 = st.columns([2, 1])
   
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
                new_visits, duplicate_visits, paid_visits = process_visits(df.copy())
               
                st.markdown("---")
               
                # Результаты обработки в три колонки
                col_result1, col_result2, col_result3 = st.columns(3)
               
                with col_result1:
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
               
                with col_result2:
                    st.subheader("⚠️ Уже оплаченные визиты")
                    if not duplicate_visits.empty:
                        st.warning(f"Найдено {len(duplicate_visits)} уже оплаченных визитов")
                       
                        # Показываем детальную информацию о дубликатах
                        for _, row in duplicate_visits.iterrows():
                            with st.expander(f"👤 {row['subject_id']} - {row['visit_name']}"):
                                st.write(f"**Текущая дата визита:** {row['visit_date']}")
                                if 'previous_visit_date' in row:
                                    st.write(f"**Ранее оплаченная дата:** {row['previous_visit_date']}")
                                    st.write(f"**Дата оплаты:** {row['previous_payment_date']}")
                               
                                # Проверяем, изменилась ли дата
                                if 'previous_visit_date' in row and row['visit_date'] != row['previous_visit_date']:
                                    st.error("🔄 **ВНИМАНИЕ:** Дата визита изменилась!")
                                else:
                                    st.info("📅 Дата визита не изменилась")
                       
                    else:
                        st.info("✅ Дубликатов не найдено")
               
                with col_result3:
                    st.subheader("📊 Анализ изменений")
                   
                    if not duplicate_visits.empty:
                        # Подсчитываем визиты с измененными датами
                        changed_dates = 0
                        unchanged_dates = 0
                       
                        for _, row in duplicate_visits.iterrows():
                            if 'previous_visit_date' in row and row['visit_date'] != row['previous_visit_date']:
                                changed_dates += 1
                            else:
                                unchanged_dates += 1
                       
                        st.metric("Визиты с измененной датой", changed_dates)
                        st.metric("Визиты с той же датой", unchanged_dates)
                       
                        if changed_dates > 0:
                            st.error("⚠️ Обратите внимание на изменения дат!")
                   
                    # Общая статистика
                    total_new = len(new_visits) if not new_visits.empty else 0
                    total_duplicates = len(duplicate_visits) if not duplicate_visits.empty else 0
                   
                    st.metric("Всего в файле", len(df))
                    st.metric("К оплате", total_new)
                    st.metric("Уже оплачены", total_duplicates)
               
                # Кнопки действий
                if not new_visits.empty:
                    st.markdown("---")
                    col_btn1, col_btn2, col_btn3 = st.columns(3)
                   
                    with col_btn1:
                        # Скачать акт оплаты
                        from io import BytesIO
                        excel_buffer = BytesIO()
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            new_visits.to_excel(writer, sheet_name='Новые визиты', index=False)
                            if not new_visits.empty:
                                summary = new_visits.groupby('subject_id').size().reset_index(name='количество_визитов')
                                summary.to_excel(writer, sheet_name='Сводка', index=False)
                            if not duplicate_visits.empty:
                                duplicate_visits.to_excel(writer, sheet_name='Уже оплаченные', index=False)
                       
                        st.download_button(
                            label="📥 Скачать отчет",
                            data=excel_buffer.getvalue(),
                            file_name=f"otchet_oplaty_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                   
                    with col_btn2:
                        if st.button("✅ Отметить новые как оплаченные", type="primary"):
                            # Добавляем информацию об оплате
                            new_visits_to_save = new_visits.copy()
                            new_visits_to_save['payment_date'] = datetime.now().strftime('%Y-%m-%d')
                            new_visits_to_save['payment_amount'] = 0.0
                           
                            # Сохраняем в базу
                            save_paid_visits(new_visits_to_save[['subject_id', 'visit_name', 'visit_date', 'payment_date', 'payment_amount']])
                           
                            st.success("✅ Новые визиты отмечены как оплаченные!")
                            st.rerun()
                   
                    with col_btn3:
                        if st.button("🔄 Обновить данные"):
                            st.rerun()
               
            except Exception as e:
                st.error(f"❌ Ошибка при обработке файла: {str(e)}")
                st.info("Убедитесь, что файл содержит данные в правильном формате")
   
    with col2:
        st.header("📈 История оплат")
        paid_visits = load_paid_visits()
       
        if not paid_visits.empty:
            # Последние оплаты
            st.subheader("🕒 Последние оплаты")
            recent_payments = paid_visits.sort_values('payment_date', ascending=False).head(10)
            for _, payment in recent_payments.iterrows():
                st.text(f"📅 {payment['payment_date']}")
                st.text(f"👤 Субъект: {payment['subject_id']}")
                st.text(f"🏥 Визит: {payment['visit_name']}")
                st.text(f"📆 Дата визита: {payment['visit_date']}")
                st.markdown("---")
        else:
            st.info("История оплат пустая")
       
        # Управление данными
        st.subheader("🛠️ Управление")
       
        if st.button("📊 Показать всю историю"):
            if not paid_visits.empty:
                st.dataframe(paid_visits, use_container_width=True)
            else:
                st.info("История пустая")
       
        if st.button("🗑️ Очистить историю", help="Удалить все записи об оплатах"):
            if st.button("⚠️ Подтвердить удаление", type="secondary"):
                conn = sqlite3.connect('payments.db')
                cursor = conn.cursor()
                cursor.execute("DELETE FROM paid_visits")
                conn.commit()
                conn.close()
                st.success("История очищена!")
                st.rerun()

if __name__ == "__main__":
    main()