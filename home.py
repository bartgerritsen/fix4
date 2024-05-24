import streamlit as st
from PIL import Image
import pickle
from pathlib import Path
import streamlit_authenticator as stauth
import pandas as pd
from datetime import datetime
import plotly.express as px
from deta import Deta

#Initialize with a project key
deta = Deta(st.secrets.deta_creds.detakey)
drive = deta.Drive("FIX4_AUTH")

#--- Webpagina configureren ---
#im = Image.open("https://www.fix4.nl/assets/files/logo-fix4-web.svg")

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

#--- USER AUTHENTICATION ---
 
names = ["FIX4"]
usernames = ["FIX4"]
hashed_passwords = pickle.loads((drive.get("hashed_pw.pkl")).read())

authenticator = stauth.Authenticate(names, usernames, hashed_passwords,
                                    "fix4_dashboard", "fix4_db_key", cookie_expiry_days=1)

name, authentication_status, username = authenticator.login("Login", "main")

st.write(f"Authentication status: {authentication_status}")

if authentication_status == False:
    st.error("Uw gebruikersnaam of wachtwoord is onjuist.")
if authentication_status == None:
    st.warning("Voer uw gebruikersnaam en wachtwoord in.")
if authentication_status == True:

    st.sidebar.header(f"Welkom, {name}!")
    authenticator.logout("Log uit", "sidebar")
    st.title("FIX4 - Zehnder Service Level Dashboard")
    st.sidebar.write("Dit dashboard is ontwikkeld door Bart Gerritsen, Trainee Business Analyst bij Zehnder Group Zwolle. Voor vragen met betrekking tot dit dashboard of de weergegeven data kunt u mailen naar bart.gerritsen@zehndergroup.com")


    def extract_huisnummer(adres):
        return adres.rsplit(' ', 1)[-1].upper()

    def werkdagen_tussen(startdatum, einddatum):
        dagen = pd.date_range(start=startdatum, end=einddatum, freq='B')  # 'B' staat voor business days (werkdagen)
        werkdagen = [dag for dag in dagen if dag.weekday() < 5]  # Filter weekenden en feestdagen
        return len(werkdagen)
    
    file1 = drive.get("fix4_dashboard.csv")
    file2 = drive.get("adressen.csv")

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
        return df
    df = fix4_data_ophalen(file1, file2)

    df['SL_1e_contact'] = df.apply(lambda row: werkdagen_tussen(row['Uitzetdatum'], row['1e Contactpoging'])-1 
                            if pd.notnull(row['Uitzetdatum']) and pd.notnull(row['1e Contactpoging']) and row['Uitzetdatum']<=row['1e Contactpoging'] else None, axis=1)
    df['SL_afspraakdatum'] = df.apply(lambda row: werkdagen_tussen(row['1e Contactpoging'], row['Afspraakdatum'])-1 
                            if pd.notnull(row['1e Contactpoging']) and pd.notnull(row['Afspraakdatum']) and row['1e Contactpoging']<=row['Afspraakdatum'] else None, axis=1)
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
        
    # Toepassen van de functie op elke rij in de dataframe
    df['Status'] = df.apply(bepaal_status, axis=1)



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
            
            if not df.shape[0] == 0:
                min_datum = st.date_input("min. datum", value = df['Uitzetdatum'].min(), min_value = df['Uitzetdatum'].min(), max_value = df['Uitzetdatum'].max(), format = 'DD-MM-YYYY')
                if bool(min_datum):
                    df = df[(df['Uitzetdatum']>=min_datum)]
                max_datum = st.date_input("max. datum", value = df['Uitzetdatum'].max(), min_value = df['Uitzetdatum'].min(), max_value = df['Uitzetdatum'].max(), format = 'DD-MM-YYYY')
                if bool(max_datum):
                    df = df[(df['Uitzetdatum']<=max_datum)]
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
        
        
        filter_url = "http://172.23.1.182:8501/Fix4"
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

        
        if df[~((df['latitude'].isna())|(df['longitude'].isna()))].shape[0] == 0:
            st.info("Geen locatiegegevens voor geselecteerde service orders gevonden", icon = "📍")
        else:
            st.map(df[~((df['latitude'].isna())|(df['longitude'].isna()))], latitude = df['latitude'], longitude = df['longitude'],size = 25, use_container_width=True)
            
        tab1, tab2 = st.tabs(['Data', 'Grafieken'])
        tab1.dataframe(df.sort_values('Uitzetdatum', ascending = False), hide_index = True, use_container_width= True)
        with tab2:
            @st.experimental_fragment
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
                    fig.add_vline(x=sla_contact_median, line_dash="dash", line_color="blue", line_width=2)
                    fig.add_annotation(
                        x=sla_contact_median,
                        y=max(df[(df['SL_1e_contact'].notna())]['SL_1e_contact'].value_counts()),
                        text=f"Mediaan ({sla_contact_median} dagen)",
                        ax=80,
                        ay=-40,
                        bgcolor="rgb(61, 61, 63)",
                        bordercolor="blue"
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
                                        plot_bgcolor='#3D3D3F', 
                                        paper_bgcolor='#3D3D3F',
                                        hovermode = "x unified",
                                        hoverlabel_font_size = 20,
                                        hoverlabel = dict(namelength = -1),
                                        bargap = 0.2
                                        )
                    div_style_aantal = '''
                                    <style>
                                        div.stPlotlyChart {
                                            border: 10px solid #3D3D3F;
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
                    fig2.add_vline(x=sla_afspraak_median, line_dash="dash", line_color="blue", line_width=2)
                    fig2.add_annotation(
                        x=sla_afspraak_median,
                        y=max(df[(df['SL_afspraakdatum'].notna())]['SL_afspraakdatum'].value_counts()),
                        text=f"Mediaan ({sla_afspraak_median} dagen)",
                        ax=80,
                        ay=-40,
                        bgcolor="rgb(61, 61, 63)",
                        bordercolor="blue"
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
                                        plot_bgcolor='#3D3D3F', 
                                        paper_bgcolor='#3D3D3F',
                                        hovermode = "x unified",
                                        hoverlabel_font_size = 20,
                                        hoverlabel = dict(namelength = -1),
                                        bargap = 0.2
                                        )
                    div_style_aantal = '''
                                    <style>
                                        div.stPlotlyChart {
                                            border: 10px solid #3D3D3F;
                                            border-radius: 20px;
                                        }
                                    </style>
                                    '''
                                    
                    st.plotly_chart(fig2, use_container_width=True)
                    st.markdown(div_style_aantal, unsafe_allow_html=True)
                else:
                    st.info('Te weinig data beschikbaar om grafiek "Frequentie van aantal dagen tussen eerste contactmoment en afspraakdatum" te plotten', icon = "❗")
                
            sla_chart(df)
