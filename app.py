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
        # Создаем ключи для сравнения
        # 1. Полный ключ: ID + название + дата (точные дубликаты)
        uploaded_df['full_key'] = uploaded_df['subject_id'].astype(str) + '_' + uploaded_df['visit_name'].astype(str) + '_' + uploaded_df['visit_date'].astype(str)
        paid_visits['full_key'] = paid_visits['subject_id'].astype(str) + '_' + paid_visits['visit_name'].astype(str) + '_' + paid_visits['visit_date'].astype(str)
        
        # 2. Частичный ключ: ID + название (тот же тип визита)
        uploaded_df['visit_type_key'] = uploaded_df['subject_id'].astype(str) + '_' + uploaded_df['visit_name'].astype(str)
        paid_visits['visit_type_key'] = paid_visits['subject_id'].astype(str) + '_' + paid_visits['visit_name'].astype(str)
        
        # 3. Ключ по дате: ID + дата (подозрительные визиты)
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
        
        # Добавляем информацию о предыдущих записях для каждой категории
        if not exact_duplicates.empty:
            exact_duplicates = exact_duplicates.merge(
                paid_visits[['full_key', 'payment_date']].rename(columns={
                    'payment_date': 'previous_payment_date'
                }),
                on='full_key',
                how='left'
            )
        
        if not same_visit_different_date.empty:
            same_visit_different_date = same_visit_different_date.merge(
                paid_visits[['visit_type_key', 'visit_date', 'payment_date']].rename(columns={
                    'visit_date': 'previous_visit_date',
                    'payment_date': 'previous_payment_date'
                }),
                on='visit_type_key',
                how='left'
            )
        
        if not suspicious_same_date.empty:
            suspicious_same_date = suspicious_same_date.merge(
                paid_visits[['date_key', 'visit_name', 'payment_date']].rename(columns={
                    'visit_name': 'previous_visit_name',
                    'payment_date': 'previous_payment_date'
                }),
                on='date_key',
                how='left'
            )
        
        # Убираем служебные столбцы
        columns_to_drop = ['full_key', 'visit_type_key', 'date_key']
        new_visits = new_visits.drop(columns_to_drop, axis=1) if not new_visits.empty else new_visits
        exact_duplicates = exact_duplicates.drop(columns_to_drop, axis=1) if not exact_duplicates.empty else exact_duplicates
        same_visit_different_date = same_visit_different_date.drop(columns_to_drop, axis=1) if not same_visit_different_date.empty else same_visit_different_date
        suspicious_same_date = suspicious_same_date.drop(columns_to_drop, axis=1) if not suspicious_same_date.empty else suspicious_same_date
        
    else:
        new_visits = uploaded_df.copy()
        exact_duplicates = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
        same_visit_different_date = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
        suspicious_same_date = pd.DataFrame(columns=['subject_id', 'visit_name', 'visit_date'])
    
    return new_visits, exact_duplicates, same_visit_different_date, suspicious_same_date, paid_visits

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
        
        **🔍 Проверка дубликатов:**
        - **Точные дубликаты**: ID + визит + дата
        - **Тот же тип визита**: ID + визит (другая дата)
        - **Подозрительные**: ID + дата (другой визит)
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
                                if 'previous_payment_date' in row:
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
                                if 'previous_visit_date' in row:
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
                                if 'previous_visit_name' in row:
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
                        from io import BytesIO
                        excel_buffer = BytesIO()
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
                            
                            # Сохраняем в базу
                            save_paid_visits(visits_to_save[['subject_id', 'visit_name', 'visit_date', 'payment_date', 'payment_amount']])
                            
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
        paid_visits = load_paid_visits()
        
        if not paid_visits.empty:
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
        
        # Управление данными (ИСПРАВЛЕННАЯ ВЕРСИЯ)
        st.subheader("🛠️ Управление")
        
        if st.button("📊 Показать всю историю", key="show_history_btn"):
            if not paid_visits.empty:
                st.dataframe(paid_visits[['subject_id', 'visit_name', 'visit_date', 'payment_date']], use_container_width=True)
            else:
                st.info("История пустая")
        
        # Используем session_state для управления состоянием удаления
        if 'confirm_delete' not in st.session_state:
            st.session_state.confirm_delete = False
        
        if not st.session_state.confirm_delete:
            if st.button("🗑️ Очистить историю", help="Удалить все записи об оплатах", key="clear_history_btn"):
                st.session_state.confirm_delete = True
                st.rerun()
        else:
            st.warning("⚠️ Вы уверены, что хотите удалить всю историю оплат?")
            
            col_confirm1, col_confirm2 = st.columns(2)
            
            with col_confirm1:
                if st.button("✅ Да, удалить", type="primary", key="confirm_delete_btn"):
                    conn = sqlite3.connect('payments.db')
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM paid_visits")
                    conn.commit()
                    conn.close()
                    st.session_state.confirm_delete = False
                    st.success("✅ История очищена!")
                    st.rerun()
            
            with col_confirm2:
                if st.button("❌ Отмена", key="cancel_delete_btn"):
                    st.session_state.confirm_delete = False
                    st.rerun()

if __name__ == "__main__":
    main()