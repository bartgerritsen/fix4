import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import plotly.express as px
from supabase import create_client
from io import StringIO
import pydeck as pdk


st.set_page_config(
    page_title="FIX4 Service Level Dashboard", 
    page_icon = "https://www.fix4.nl/assets/files/logo-fix4-web.svg",
    layout = 'wide',
    initial_sidebar_state= "expanded"
)
# --- Styling van de webpagina ---
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
st.sidebar.image("https://www.fix4.nl/assets/files/logo-fix4-web.svg", use_column_width=True)
st.sidebar.subheader("")
st.markdown(
            """
            <style>
            [data-testid="stMetricDelta"] svg {
                display: none;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
entity_select = st.sidebar.selectbox("Inloggen als", options = ['FIX4', 'Zehnder', 'Admin'], key = 'entity')
key_input = st.sidebar.text_input("Secret key", type = 'password', key = 'pw')

if entity_select == 'FIX4':
    pw = st.secrets['credentials']["pw_fix4"]
    naam = 'FIX4'
elif entity_select == 'Zehnder':
    pw = st.secrets['credentials']["pw_zehnder"]
    naam = 'Zehnder'
elif entity_select == 'Admin':
    pw = st.secrets['credentials']["pw_admin"]
    naam = 'Admin'

if pw == key_input:
    authentication_status = True
elif len(key_input) == 0:
    authentication_status = None
else:
    authentication_status = False

if authentication_status == False:
    st.error("De ingevoerde Secret Key is onjuist.")
if authentication_status == None:
    st.info("Specificeer de gebruiker en voer de Secret Key in de sidebar links in om verder te gaan.", icon = "🚀")
if authentication_status == True:

    url = st.secrets.supabase_creds.url
    key = st.secrets.supabase_creds.key
    supabase = create_client(url, key)
    bucket_name = "fix4"

    st.sidebar.header(f"Welkom, {naam}!")
    data = {'name': naam,
            'last_activity': str(datetime.now()),
            'key': f'{naam}-{str((datetime.now()).strftime("%Y-%m-%d-%H"))}'
    }
    
    supabase.table('EXTERN_LOGIN').upsert(data).execute()

    if st.button(f"Refresh", type = 'primary', help = "Klik hier om de pagina te refreshen"):
        st.cache_data.clear()
    
    if naam == 'Admin':
        st.subheader("Log Externe Users")
        log_data = pd.DataFrame((supabase.table('EXTERN_LOGIN').select("*").execute()).data)
        log_data['last_activity'] = pd.to_datetime(log_data['last_activity']).dt.strftime('%d-%m-%Y %H:%M:%S')
        log_data_grouped = log_data.groupby('name').agg(
            last_activity=('last_activity', 'max'),
            active_hours_past_30_days=('last_activity', 'size')
        ).reset_index()
        st.dataframe(log_data_grouped, hide_index = True)
    
    st.markdown('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,100,0,0"/>', unsafe_allow_html=True)
    st.markdown("""<div style="display: flex; align-items: center;"><span class="material-symbols-outlined" style="font-size:48px; margin-right:15px;">engineering</span><h1 style="margin: 0;">FIX4 - Zehnder Service Level Dashboard</h1></div>""",unsafe_allow_html=True)
    st.sidebar.write("Dit dashboard is ontwikkeld door Bart Gerritsen, Trainee Business Analyst bij Zehnder Group Zwolle. Voor vragen met betrekking tot dit dashboard of de weergegeven data kunt u mailen naar bart.gerritsen@zehndergroup.com")

    def extract_huisnummer(adres):
        return adres.rsplit(' ', 1)[-1].upper()

    def werkdagen_tussen(startdatum, einddatum):
        dagen = pd.date_range(start=startdatum, end=einddatum, freq='B')  # 'B' staat voor business days (werkdagen)
        werkdagen = [dag for dag in dagen if dag.weekday() < 5]  # Filter weekenden en feestdagen
        return len(werkdagen)
    
    file1_bytes = supabase.storage.from_(bucket_name).download("fix4_dashboard.csv")
    file2_bytes = supabase.storage.from_(bucket_name).download("adressen.csv")

    file1 = StringIO(file1_bytes.decode('utf-8'))
    file2 = StringIO(file2_bytes.decode('utf-8'))

    def bepaal_status(row):
        if row['Administratieve Fase'] == 'Actief':
            if pd.isnull(row['Afspraakdatum']) and pd.isnull(row['1e Contactpoging']):
                return 'Openstaand'
            elif row['1e Contactpoging'] and pd.isnull(row['Afspraakdatum']) and row['Status Fase'] == 'Aanmaak':
                return 'Inplannen'
            elif row['Afspraakdatum'] and row['Afspraakdatum'].weekday() >= 5 and row['Status Fase'] == 'Aanmaak':
                return 'Inplannen'
            elif row['Afspraakdatum'] and row['Afspraakdatum'] > datetime.now().date() and row['Status Fase'] in ['Aanmaak', 'In uitvoering']:
                return 'Gepland'
            elif row['Afspraakdatum'] and row['Afspraakdatum'] == datetime.now().date() and row['Status Fase'] in ['Aanmaak', 'In uitvoering']:
                return 'In uitvoering'
            elif row['Status Fase'] == 'Uitgevoerd':
                return 'Afgerond'
            elif row['Afspraakdatum'] < datetime.now().date() and row['Status Fase'] in ['Aanmaak', 'In uitvoering']:
                return 'Wachten op afronding'
        elif row['Administratieve Fase'] == 'Vervallen':
            return 'Vervallen'
        else:
            return 'Onbekend'

    def add_sl_columns(df: pd.DataFrame) -> pd.DataFrame:
        """
        Voeg kolommen SL_1e_contact en SL_afspraakdatum toe aan df,
        berekend met numpy.busday_count en met pandas Int64 dtype voor missing values.
        """
        # 1) Datumkolommen als datetime (NaT bij ongeldige waarden)
        df = df.copy()
        df['Uitzetdatum']       = pd.to_datetime(df['Uitzetdatum'],       errors='coerce')
        df['1e Contactpoging']  = pd.to_datetime(df['1e Contactpoging'],  errors='coerce')
        df['Afspraakdatum']     = pd.to_datetime(df['Afspraakdatum'],     errors='coerce')

        # 2) Omzetten naar datetime64[D] arrays
        start1 = df['Uitzetdatum'].to_numpy(dtype='datetime64[D]')
        end1   = df['1e Contactpoging'].to_numpy(dtype='datetime64[D]')
        start2 = df['1e Contactpoging'].to_numpy(dtype='datetime64[D]')
        end2   = df['Afspraakdatum'].to_numpy(dtype='datetime64[D]')

        # 3) Masks bepalen
        mask1 = df['Uitzetdatum'].notna() & df['1e Contactpoging'].notna() & (start1 <= end1)
        mask2 = df['1e Contactpoging'].notna() & df['Afspraakdatum'].notna()    & (start2 <= end2)

        # 4) Busday counts berekenen
        wb1 = np.busday_count(start1[mask1], end1[mask1]) 
        wb2 = np.busday_count(start2[mask2], end2[mask2]) 

        # 5) Series met Int64 dtype maken en vullen
        result1 = pd.Series(pd.NA, index=df.index, dtype="Int64")
        result1.loc[mask1] = wb1

        result2 = pd.Series(pd.NA, index=df.index, dtype="Int64")
        result2.loc[mask2] = wb2

        # 6) Toevoegen aan DataFrame
        df['SL_1e_contact']    = result1
        df['SL_afspraakdatum'] = result2

        # 7) gebruikte datetimes omzetten naar datums
        df['1e Contactpoging'] = df['1e Contactpoging'].dt.date
        df['Uitzetdatum'] = df['Uitzetdatum'].dt.date
        df['Afspraakdatum'] = df['Afspraakdatum'].dt.date
        return df

    @st.cache_data(show_spinner = "Data ophalen...")
    def fix4_data_ophalen(_pad, _pad2):
        df = pd.read_csv(_pad)
        df['Huisnummer'] = df['Adres'].apply(extract_huisnummer)
        df['Postcode'] = df['Postcode'].str.replace(' ', '')
        df_adressen = pd.read_csv(_pad2)
        df_adressen = df_adressen.rename(columns = {'postcode': 'Postcode', 'huisnummer': 'Huisnummer', 'provincie': 'Provincie'})
        df = pd.merge(df, df_adressen, on = ['Postcode', 'Huisnummer'], how= 'left')
        df_adressen = df_adressen.groupby('Postcode', observed = False)[['latitude', 'longitude']].mean().reset_index()
        df_adressen = df_adressen.rename(columns = {'latitude': 'latitude_gem', 'longitude':'longitude_gem'})
        df = pd.merge(df, df_adressen, on = 'Postcode', how = 'left')
        df['longitude'].fillna(df['longitude_gem'], inplace = True)
        df['latitude'].fillna(df['latitude_gem'], inplace = True)
        df.drop(['Huisnummer', 'latitude_gem', 'longitude_gem'], axis = 1, inplace = True)
        df['Uitzetdatum'] = pd.to_datetime(df['Uitzetdatum'], format='%d-%m-%Y').dt.date
        df['1e Contactpoging'] = pd.to_datetime(df['1e Contactpoging'], format='%d-%m-%Y').dt.date
        df['Afspraakdatum'] = pd.to_datetime(df['Afspraakdatum'], format='%d-%m-%Y').dt.date
        df['Provincie'] = df['Provincie'].fillna('Onbekend')
        columns_to_strip = ['Unit', 'Referentie', 'SO-nummer', 'Adres', 'Werkzaamheden', 'Status Fase', 'Administratieve Fase']
        for column in columns_to_strip:
            df[column] = df[column].str.strip()
        df['Werkzaamheden'] = df['Werkzaamheden'].str.lower().fillna("onbekend")
        df = add_sl_columns(df)
        df['Status'] = df.apply(bepaal_status, axis=1)
        return df
    
    df = fix4_data_ophalen(file1, file2)
        
    with st.popover("Filter", use_container_width=True, help = "Klik hier om de data te filteren"):
        with st.form("filter"):
            werkzaamheden = st.multiselect("Werkzaamheden", sorted(df['Werkzaamheden'].astype(str).unique()), placeholder = "Werkzaamheden...")
            if bool(werkzaamheden):
                df = df[df['Werkzaamheden'].isin(werkzaamheden)]
            unit = st.multiselect("Unit", options = sorted(df['Unit'].unique().astype(str)), placeholder = 'Unit...')
            if bool(unit):
                df = df[df['Unit'].isin(unit)]
            ref_nummer = st.multiselect("Referentie", options = sorted(df['Referentie'].unique().astype(str)), placeholder = 'Referentie...')
            if bool(ref_nummer):
                df = df[df['Referentie'].isin(ref_nummer)]
            so_nummer = st.multiselect("SO-nr.", options = sorted(df['SO-nummer'].unique().astype(str)), placeholder = 'SO-nummer...')
            if bool(so_nummer):
                df = df[df['SO-nummer'].isin(so_nummer)]
            status = st.multiselect("Status", options = sorted(df['Status Fase'].unique().astype(str)), placeholder = 'Status...')
            if bool(status):
                df = df[df['Status Fase'].isin(status)]
            ad_status = st.multiselect("Administratieve status", options = sorted(df['Administratieve Fase'].unique().astype(str)), placeholder = 'Administratieve status...')
            if bool(ad_status):
                df = df[df['Administratieve Fase'].isin(ad_status)] 
            postcode = st.text_input("Postcode", max_chars = 6, placeholder = "Postcode begint met...")
            if bool(postcode):
                df = df[df['Postcode'].str.startswith(str(postcode))]
            provincie = st.multiselect("Provincie", options = sorted(df['Provincie'].unique().astype(str)), placeholder = 'Provincie...')
            if bool(provincie):    
                df = df[df['Provincie'].isin(provincie)]
            
            if date.today() < date(2025, 9, 1):
                st.info("Nieuw! Met behulp van 'Choose a date range' kun je snel een datuminterval selecteren. Probeer het hieronder uit!", icon = "🚀")
            if not df.shape[0] == 0:
                s = pd.to_datetime(df['Uitzetdatum'], errors='coerce')

                smin, smax = s.min(), s.max()
                min_date = smin.date() if pd.notna(smin) else datetime.date.today()
                max_date = (max(smax.date(), date.today()) + timedelta(days = 1)) if pd.notna(smax) else date.today()  # cap op vandaag

                if min_date > max_date:
                    min_date = max_date

                datum_select = st.date_input("min. datum", value = [min_date, max_date], min_value = min_date, max_value = max_date, format = 'DD-MM-YYYY')
                if datum_select != (min_date, max_date):
                    df = df[
                        (df['Uitzetdatum'] >= datum_select[0]) &
                        (df['Uitzetdatum'] <= datum_select[1])
                    ]
                x = 0
            else:
                x = 1
            
            st.form_submit_button("Bevestigen", type = 'primary', use_container_width= True)
    alles = df.shape[0]
    openstaand = df[df['Status']=='Openstaand'].shape[0]
    inplannen = df[df['Status']=='Inplannen'].shape[0]
    gepland = df[df['Status']=='Gepland'].shape[0]
    in_uitvoering = df[df['Status']=='In uitvoering'].shape[0]
    afgerond = df[df['Status']=='Afgerond'].shape[0]
    wachten_op_afronding = df[df['Status']=='Wachten op afronding'].shape[0]
    vervallen = df[df['Status']=='Vervallen'].shape[0]

    if 'filter_value' not in st.session_state:
        st.session_state['filter_value'] = 'total'
    elif st.session_state['filter_value'] == 'openstaand':
        df = df[df['Status']=='Openstaand']
    elif st.session_state['filter_value'] == 'inplannen':
        df = df[df['Status']=='Inplannen']
    elif st.session_state['filter_value'] == 'gepland':
        df = df[df['Status']=='Gepland']
    elif st.session_state['filter_value'] == 'wachten_op_afronding':
        df = df[df['Status']=='Wachten op afronding']
    elif st.session_state['filter_value'] == 'afgerond':
        df = df[df['Status']=='Afgerond']
    elif st.session_state['filter_value'] == 'vervallen':
        df = df[df['Status']=='Vervallen']
    else:
        pass

    if x == 1:
        st.info("Geen service orders gevonden die voldoen aan de gestelde criteria", icon = "❗")
        st.stop()
    else:
        m1,m2,m3,m4,m5,m6,m7 = st.columns(7)
        
    
        with m1:
            with st.container(border = True):
                st.metric("Alle service orders", value = alles)
                if st.session_state['filter_value'] == 'total':
                    button = "Geselecteerd ✅"
                else:
                    button = "Selecteer"
                if st.button(button, key = "total", use_container_width=True):
                    st.session_state['filter_value'] = 'total'
                    st.rerun()
        with m2:
            with st.container(border = True):
                st.metric("Openstaand", value = openstaand)
                if st.session_state['filter_value'] == 'openstaand':
                    button = "Geselecteerd ✅"
                else:
                    button = "Selecteer"
                if st.button(button, key = "openstaand",  use_container_width=True):
                    st.session_state['filter_value'] = 'openstaand'
                    st.rerun()
                
        with m3:
            with st.container(border = True):
                st.metric("Inplannen", value = inplannen)
                if st.session_state['filter_value'] == 'inplannen':
                    button = "Geselecteerd ✅"
                else:
                    button = "Selecteer"
                if st.button(button, key = "inplannen",  use_container_width=True):
                    st.session_state['filter_value'] = 'inplannen'
                    st.rerun()
        with m4:
            with st.container(border = True):
                st.metric("Gepland", value = gepland)
                if st.session_state['filter_value'] == 'gepland':
                    button = "Geselecteerd ✅"
                else:
                    button = "Selecteer"
                if st.button(button, key = "gepland",  use_container_width=True):
                    st.session_state['filter_value'] = 'gepland'
                    st.rerun()
        with m5:
            with st.container(border = True):
                st.metric("Wachten op afronding", value = wachten_op_afronding)
                if st.session_state['filter_value'] == 'wachter_op_afronding':
                    button = "Geselecteerd ✅"
                else:
                    button = "Selecteer"
                if st.button(button, key = "wachten_op_afronding",  use_container_width=True):
                    st.session_state['filter_value'] = 'wachten_op_afronding'
                    st.rerun()
        with m6:
            with st.container(border = True):
                st.metric("Afgerond", value = afgerond)
                if st.session_state['filter_value'] == 'afgerond':
                    button = "Geselecteerd ✅"
                else:
                    button = "Selecteer"
                if st.button(button, key = "afgerond",  use_container_width=True):
                    st.session_state['filter_value'] = 'afgerond'
                    st.rerun()
        with m7:
            with st.container(border = True):
                st.metric("Vervallen", value = vervallen)
                if st.session_state['filter_value'] == 'vervallen':
                    button = "Geselecteerd ✅"
                else:
                    button = "Selecteer"
                if st.button(button, key = "vervallen",  use_container_width=True):
                    st.session_state['filter_value'] = 'vervallen'
                    st.rerun()

        
        @st.fragment()
        def display_map(df):
            if "map_selections" in st.session_state:
                selected_objects = st.session_state["map_selections"]['selection']['objects']
                if selected_objects:
                    for key, value in selected_objects.items():
                        if isinstance(value, list) and len(value) > 0:
                            referentie_filter = value[0].get("Referentie")  # Verkrijg de referentie van de eerste item in de lijst
                            so_nummer_filter = value[0].get("SO-nummer")
                            df = df[(df['SO-nummer']==so_nummer_filter)&(df['Referentie']==referentie_filter)]
                            st.dataframe(df, hide_index = True, key = 'map_filtered_df', use_container_width=True)
                            scat_rad = 50
                            break  # Stop de loop als we de referentie hebben gevonden
                    if st.button("Annuleer kaart-selectie", key = 'deselect_map', use_container_width=True):
                        del st.session_state['map_selections']
                        scat_rad = 20
                else:
                    scat_rad = 20
            else:
                scat_rad = 20

            if df[~((df['latitude'].isna())|(df['longitude'].isna()))].shape[0] == 0:
                st.info("Geen locatiegegevens voor geselecteerde service orders gevonden", icon = "📍")
            else:
                map_selections = st.pydeck_chart(
                    pdk.Deck(
                        map_style = None,
                        initial_view_state = pdk.ViewState(
                            latitude = 52.1004,
                            longitude = 5.6226,
                            zoom = 6,
                            
                        ),
                        layers = [
                            pdk.Layer(
                                "ScatterplotLayer",
                                data = df[~((df['latitude'].isna())|(df['longitude'].isna()))][['longitude', 'latitude', 'Referentie', 'SO-nummer', 'Adres', 'Unit', 'Werkzaamheden', 'Status']],
                                get_position = "[longitude, latitude]",
                                get_color = "[200, 30, 0, 160]",
                                get_radius = scat_rad,
                                radiusMinPixels = 2
                            ),
                        ], tooltip = {"text": "Referentie: {Referentie}\nSO-nummer: {SO-nummer}\nAdres: {Adres}\nUnit: {Unit}\nWerkzaamheden: {Werkzaamheden}\nStatus: {Status}"}
                    ), on_select="rerun", key = 'map_selections'
                )
            
        display_map(df)
            
        tab1, tab2 = st.tabs(['Data', 'Grafieken'])
        tab1.dataframe(df.sort_values('Uitzetdatum', ascending = False), hide_index = True, use_container_width= True)
        with tab2:
            df = df[df['Status']!='Vervallen']
            
            @st.fragment
            def sla_chart(df):
                with st.popover("Grafiekinstellingen"):
                    bin_size = st.number_input("Aantal dagen per staaf", min_value = 1, max_value = 10, step = 1, value = 1, help = "Hiermee selecteer je hoeveel dagen in het interval van één staaf weergegeven worden.")
                    col1, col2 = st.columns(2)
                    col1.subheader("SLA: contact")
                    sla_contact = col1.slider("SLA: uitzetdatum - contact", min_value = 0, max_value = 21, step = 1, value = 5, help = "Hiermee specificeer je het afgesproken service level voor het aantal dagen tussen de uitzetdatum en het eerste contactmoment van een service order.")
                    
                    col2.subheader("SLA: afspraak")
                    sla_afspraak = col2.slider("SLA: contact - afspraak", min_value = 0, max_value = 21, step = 1, value = 5, help = "Hiermee specificeer je het afgesproken service level voor het aantal dagen tussen het eerste contactmomenten de uiteindelijke afspraakdatum van een service order.")
                if df[(df['SL_1e_contact'].notna())].shape[0] >0:
                    binnen_sla_contact_abs = df[(df['SL_1e_contact']<=sla_contact) & (df['SL_1e_contact'].notna())].shape[0]
                    binnen_sla_contact = round((binnen_sla_contact_abs / df[(df['SL_1e_contact'].notna())].shape[0])*100, 2)
                    sla_contact_median = (pd.to_numeric(df[(df['SL_1e_contact'].notna())]['SL_1e_contact'], errors = 'coerce').median()).astype(int)
                    st.metric("Binnen SLA uitzetdatum - contact", f"{binnen_sla_contact_abs} ({binnen_sla_contact}%)")
                
                    fig = px.histogram(
                                    df,
                                    x="SL_1e_contact",
                                    title="Frequentie van aantal dagen tussen uitzetdatum en eerste contactmoment",
                    )
                    fig.update_traces(xbins=dict(size=bin_size))
                    fig.update_traces(textfont_size=14, textangle=0, textposition="outside", cliponaxis=False, hovertemplate = None, name = "Aantal dagen")
                    fig.add_vline(x=sla_contact, line_dash="dash", line_color="red", line_width=2)
                    fig.add_vline(x=sla_contact_median, line_dash="dash", line_color="#009E46", line_width=2)
                    fig.add_annotation(
                        x=sla_contact_median,
                        y=max(df[(df['SL_1e_contact'].notna())]['SL_1e_contact'].value_counts()),
                        text=f"Mediaan ({sla_contact_median} dag(en))",
                        ax=80,
                        ay=-40,
                        bgcolor="rgb(242, 242, 242)",
                        bordercolor="#009E46"
                    )
                    fig.update_layout( 
                                        xaxis_tickangle=-50,
                                        xaxis=dict(title = 'Aantal dagen tussen uitzetdatum en eerste contactmoment'),
                                        yaxis=dict(title='Aantal serviceorders'),
                                        margin=dict(l=0, r=0, t=30, b=0),
                                        width=600,
                                        height=400,
                                        uniformtext_minsize = 12,
                                        uniformtext_mode = 'hide',
                                        plot_bgcolor='#F2F2F2', 
                                        paper_bgcolor='#F2F2F2',
                                        hovermode = "x unified",
                                        hoverlabel_font_size = 20,
                                        hoverlabel = dict(namelength = -1),
                                        bargap = 0.2
                                        )
                    div_style_aantal = '''
                                    <style>
                                        div.stPlotlyChart {
                                            border: 10px solid #F2F2F2;
                                            border-radius: 20px;
                                        }
                                    </style>
                                    '''
                                    
                    st.plotly_chart(fig, use_container_width=True)
                    st.markdown(div_style_aantal, unsafe_allow_html=True)
                else:
                    st.info('Te weinig data beschikbaar om grafiek "Frequentie van aantal dagen tussen uitzetdatum en eerste contactmoment" te plotten', icon = "❗")
                
                if df[(df['SL_afspraakdatum'].notna())].shape[0] > 0:
                    binnen_sla_afspraak_abs = df[(df['SL_afspraakdatum']<=sla_afspraak) & (df['SL_afspraakdatum'].notna())].shape[0]
                    binnen_sla_afspraak = round((binnen_sla_afspraak_abs / df[(df['SL_afspraakdatum'].notna())].shape[0])*100, 2)
                    sla_afspraak_median = (pd.to_numeric(df[(df['SL_afspraakdatum'].notna())]['SL_afspraakdatum'], errors = 'coerce').median()).astype(int)
                    st.metric("Binnen SLA contact - afspraak", f"{binnen_sla_afspraak_abs} ({binnen_sla_afspraak}%)")
                    
                    fig2 = px.histogram(
                                    df,
                                    x="SL_afspraakdatum",                     
                                    title="Frequentie van aantal dagen tussen eerste contactmoment en afspraakdatum")
                    fig2.update_traces(xbins=dict(size=bin_size))
                    fig2.update_traces(textfont_size=14, textangle=0, textposition="outside", cliponaxis=False, hovertemplate = None, name = "Aantal dagen")
                    fig2.add_vline(x=sla_afspraak, line_dash="dash", line_color="red", line_width=2)
                    fig2.add_vline(x=sla_afspraak_median, line_dash="dash", line_color="#009E46", line_width=2)
                    fig2.add_annotation(
                        x=sla_afspraak_median,
                        y=max(df[(df['SL_afspraakdatum'].notna())]['SL_afspraakdatum'].value_counts()),
                        text=f"Mediaan ({sla_afspraak_median} dag(en))",
                        ax=80,
                        ay=-40,
                        bgcolor="rgb(242, 242, 242)",
                        bordercolor="#009E46"
                    )
                    fig2.update_layout( 
                                        xaxis_tickangle=-50,
                                        xaxis=dict(title = 'Aantal dagen tussen eerste contactmoment en afspraakdatum'),
                                        yaxis=dict(title='Aantal serviceorders'),
                                        margin=dict(l=0, r=0, t=30, b=0),
                                        width=600,
                                        height=400,
                                        uniformtext_minsize = 12,
                                        uniformtext_mode = 'hide',
                                        plot_bgcolor='#F2F2F2', 
                                        paper_bgcolor='#F2F2F2',
                                        hovermode = "x unified",
                                        hoverlabel_font_size = 20,
                                        hoverlabel = dict(namelength = -1),
                                        bargap = 0.2
                                        )
                    div_style_aantal = '''
                                    <style>
                                        div.stPlotlyChart {
                                            border: 10px solid #F2F2F2;
                                            border-radius: 20px;
                                        }
                                    </style>
                                    '''
                                    
                    st.plotly_chart(fig2, use_container_width=True)
                    st.markdown(div_style_aantal, unsafe_allow_html=True)
                else:
                    st.info('Te weinig data beschikbaar om grafiek "Frequentie van aantal dagen tussen eerste contactmoment en afspraakdatum" te plotten', icon = "❗")
                
            sla_chart(df)
