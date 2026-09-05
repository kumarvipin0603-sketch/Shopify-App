from pathlib import Path
import io, shutil
import pandas as pd
import streamlit as st
from reconciliation import SOURCE_FILES, available_sources, build_control_tower, source_path

BASE=Path(__file__).resolve().parent
DATA=BASE/'data'
DATA.mkdir(exist_ok=True)

st.set_page_config(page_title='Website Order Control Tower',page_icon='📦',layout='wide')
st.markdown('''<style>
.block-container{padding-top:1.2rem;padding-bottom:2rem}.stMetric{border:1px solid #e7e7e7;border-radius:10px;padding:12px;background:white}
.small-note{color:#666;font-size:.88rem}.status-ok{color:#16794b}.status-warn{color:#b36b00}
</style>''',unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def load_tower(version=0):
    return build_control_tower(DATA)

if 'data_version' not in st.session_state: st.session_state.data_version=0

st.title('Website Order Control Tower')
st.caption('Order → Fulfilment → Billing → Payment → Settlement → Refund/CN → Closure')

with st.sidebar:
    st.header('Navigation')
    page=st.radio('', ['Dashboard','Order Control Tower','Exceptions','Payment Reconciliation','Upload Centre','Source Health'],label_visibility='collapsed')
    st.divider()
    st.caption('Glen Website Orders • Local dashboard')

ct,matches,unmatched,raw=load_tower(st.session_state.data_version)

# Global order-date filter used across every analytical navigation page.
def apply_global_date_filter(ct, matches):
    if ct.empty or 'Created at' not in ct.columns:
        return ct, matches, 'All dates'
    dates=pd.to_datetime(ct['Created at'],errors='coerce')
    valid=dates.dropna()
    if valid.empty:
        return ct, matches, 'All dates'
    min_d=valid.min().date(); max_d=valid.max().date()
    with st.sidebar:
        st.divider()
        st.subheader('Date Filter')
        mode=st.selectbox('Period',['Date Range','Weekly','Monthly','Quarterly','Half Yearly','Yearly'],key='global_period_mode')
        start=min_d; end=max_d; label=f'{min_d:%d %b %Y} – {max_d:%d %b %Y}'
        if mode=='Date Range':
            picked=st.date_input('Order Date Range',value=(min_d,max_d),min_value=min_d,max_value=max_d,key='global_date_range')
            if isinstance(picked,(tuple,list)) and len(picked)==2:
                start,end=picked
            elif picked:
                start=end=picked
            label=f'{start:%d %b %Y} – {end:%d %b %Y}'
        else:
            tmp=pd.DataFrame({'d':valid})
            if mode=='Weekly':
                iso=tmp['d'].dt.isocalendar(); tmp['key']=iso['year'].astype(str)+'-W'+iso['week'].astype(str).str.zfill(2)
                tmp['label']=tmp['d'].dt.to_period('W-MON').astype(str)
            elif mode=='Monthly':
                tmp['key']=tmp['d'].dt.to_period('M').astype(str); tmp['label']=tmp['d'].dt.strftime('%b %Y')
            elif mode=='Quarterly':
                tmp['key']=tmp['d'].dt.to_period('Q').astype(str); tmp['label']='Q'+tmp['d'].dt.quarter.astype(str)+' '+tmp['d'].dt.year.astype(str)
            elif mode=='Half Yearly':
                half=((tmp['d'].dt.month-1)//6+1); tmp['key']=tmp['d'].dt.year.astype(str)+'-H'+half.astype(str); tmp['label']='H'+half.astype(str)+' '+tmp['d'].dt.year.astype(str)
            else:
                tmp['key']=tmp['d'].dt.year.astype(str); tmp['label']=tmp['key']
            periods=tmp[['key','label']].drop_duplicates().sort_values('key',ascending=False)
            options=periods['key'].tolist(); labels=dict(zip(periods['key'],periods['label']))
            chosen=st.selectbox(f'Select {mode}',options,index=0,format_func=lambda x:labels.get(x,x),key=f'global_{mode}')
            dsel=tmp.loc[tmp['key']==chosen,'d']; start=dsel.min().date(); end=dsel.max().date(); label=labels.get(chosen,chosen)
        st.caption(f'Applied: {label}')
    mask=(dates.dt.date>=start)&(dates.dt.date<=end)
    filtered=ct.loc[mask].copy()
    if not matches.empty and 'Order No' in matches.columns:
        matches=matches[matches['Order No'].isin(set(filtered['Order No']))].copy()
    return filtered,matches,label

ct,matches,date_filter_label=apply_global_date_filter(ct,matches)

if page=='Upload Centre':
    st.subheader('Data Upload Centre')
    st.write('Upload each source independently. Existing source files are replaced only for that source; the dashboard recalculates automatically.')
    cols=st.columns(2)
    for i,(source,fname) in enumerate(SOURCE_FILES.items()):
        with cols[i%2]:
            exists=source_path(DATA,source).exists()
            st.markdown(f"**{source}**  {'✅ Loaded' if exists else '⏳ Pending'}")
            up=st.file_uploader(f'Upload {source}',type=['xlsx','xls','csv'],key=f'up_{source}')
            if up is not None:
                if st.button(f'Save / Replace {source}',key=f'save_{source}',use_container_width=True):
                    target=source_path(DATA,source)
                    target.write_bytes(up.getbuffer())
                    st.session_state.data_version += 1
                    st.cache_data.clear()
                    st.success(f'{source} updated.')
                    st.rerun()
    st.divider()
    st.info('Website Team Update can be uploaded later. Logistics files can also be added without changing the dashboard architecture.')

elif ct.empty:
    st.error('Shopify Orders is required to build the control tower. Please upload it in Upload Centre.')

elif page=='Dashboard':
    st.caption(f'Order date: {date_filter_label}')
    total=len(ct); value=ct['Total'].sum(); cancelled=(ct['Order Status']=='Cancelled').sum(); fulfilled=(ct['Fulfilment Status']=='Fulfilled').sum(); billed=(ct['Billing Status']=='Billed').sum(); unsettled=(ct['Settlement Status']=='Unsettled').sum(); action=(ct['Final Closure']=='Action Required').sum()
    a,b,c,d,e,f=st.columns(6)
    a.metric('Orders',f'{total:,}'); b.metric('Order Value',f'₹{value/1e7:.2f} Cr'); c.metric('Cancelled',f'{cancelled:,}'); d.metric('Fulfilled',f'{fulfilled:,}'); e.metric('Billed',f'{billed:,}'); f.metric('Action Required',f'{action:,}')
    st.divider()
    c1,c2=st.columns(2)
    with c1:
        st.markdown('#### Lifecycle Status')
        life=pd.DataFrame({'Status':['Fulfilled','Unfulfilled','Billed','Unbilled','Settled','Unsettled'], 'Orders':[(ct['Fulfilment Status']=='Fulfilled').sum(),(ct['Fulfilment Status']=='Unfulfilled').sum(),(ct['Billing Status']=='Billed').sum(),(ct['Billing Status']=='Unbilled').sum(),(ct['Settlement Status']=='Settled').sum(),unsettled]}).set_index('Status')
        st.bar_chart(life)
    with c2:
        st.markdown('#### Final Closure')
        st.bar_chart(ct['Final Closure'].value_counts())
    st.markdown('#### Recent orders requiring action')
    show=ct[ct['Final Closure']=='Action Required'].head(50)
    st.dataframe(show[['Order No','Created at','Total','Order Status','Fulfilment Status','Billing Status','Payment Status','Settlement Status','CN Status','Exception Reason']],use_container_width=True,hide_index=True)

elif page=='Order Control Tower':
    st.subheader('Order-Level Control Tower')
    st.caption(f'Order date: {date_filter_label}')
    f1,f2,f3,f4=st.columns(4)
    q=f1.text_input('Search order / invoice / customer / SKU')
    order_status=f2.multiselect('Order Status',sorted(ct['Order Status'].dropna().unique()))
    billing=f3.multiselect('Billing Status',sorted(ct['Billing Status'].dropna().unique()))
    settlement=f4.multiselect('Settlement Status',sorted(ct['Settlement Status'].dropna().unique()))
    view=ct.copy()
    if q:
        mask=view.astype(str).apply(lambda s:s.str.contains(q,case=False,na=False)).any(axis=1); view=view[mask]
    if order_status:view=view[view['Order Status'].isin(order_status)]
    if billing:view=view[view['Billing Status'].isin(billing)]
    if settlement:view=view[view['Settlement Status'].isin(settlement)]
    st.caption(f'{len(view):,} orders shown')
    st.dataframe(view,use_container_width=True,hide_index=True,height=600)
    bio=io.BytesIO()
    with pd.ExcelWriter(bio,engine='xlsxwriter') as writer: view.to_excel(writer,index=False,sheet_name='Order Control Tower')
    st.download_button('Download filtered control tower',bio.getvalue(),'order_control_tower.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    st.divider()
    st.markdown('#### Order drill-down')
    ono=st.selectbox('Select Order No',view['Order No'].tolist()[:5000] if len(view) else [])
    if ono:
        r=ct[ct['Order No']==ono].iloc[0]
        k1,k2,k3,k4=st.columns(4); k1.metric('Order Value',f"₹{r['Total']:,.0f}"); k2.metric('Billing',r['Billing Status']); k3.metric('Payment',r['Payment Status']); k4.metric('Closure',r['Final Closure'])
        st.dataframe(pd.DataFrame({'Field':r.index,'Value':[str(x) for x in r.values]}),use_container_width=True,hide_index=True)
        if not matches.empty:
            st.markdown('##### Matched payment transactions')
            st.dataframe(matches[matches['Order No']==ono],use_container_width=True,hide_index=True)

elif page=='Exceptions':
    st.subheader('Exception Control Tower')
    st.caption(f'Order date: {date_filter_label}')
    ex=ct[ct['Exception Reason'].ne('')].copy()
    reasons=sorted(set(x.strip() for s in ex['Exception Reason'] for x in str(s).split(';') if x.strip()))
    sel=st.multiselect('Exception type',reasons)
    if sel: ex=ex[ex['Exception Reason'].apply(lambda x:any(s in str(x) for s in sel))]
    st.metric('Orders requiring action',f'{len(ex):,}')
    st.dataframe(ex[['Order No','Created at','Billing Name','Total','Order Status','Fulfilment Status','Billing Status','Payment Status','Settlement Status','CN Status','Exception Reason']],use_container_width=True,hide_index=True,height=620)

elif page=='Payment Reconciliation':
    st.subheader('Payment & Settlement Reconciliation')
    st.caption(f'Order date: {date_filter_label}')
    if matches.empty: st.warning('No exact gateway matches found.')
    else:
        p1,p2,p3=st.columns(3); p1.metric('Matched transactions',f'{len(matches):,}'); p2.metric('Matched collection',f"₹{matches['Txn_Amount'].sum():,.0f}"); p3.metric('Net settlement',f"₹{matches['Net_Settlement'].sum():,.0f}")
        g=matches.groupby('Gateway',as_index=False).agg(Transactions=('Order No','size'),Collection=('Txn_Amount','sum'),Settlement=('Net_Settlement','sum'))
        st.dataframe(g,use_container_width=True,hide_index=True)
        st.dataframe(matches.sort_values('Settlement_Date',ascending=False),use_container_width=True,hide_index=True,height=480)
    st.markdown('#### Unmatched gateway rows')
    st.caption('These are deliberately not force-matched. They need a trustworthy Shopify reference or later manual mapping logic.')
    for source,df in unmatched:
        with st.expander(f'{source}: {len(df):,} unmatched rows'):
            st.dataframe(df.head(300),use_container_width=True,hide_index=True)

elif page=='Source Health':
    st.subheader('Source Health')
    av=available_sources(DATA)
    rows=[]
    for s,ok in av.items():
        path=source_path(DATA,s)
        rows.append({'Source':s,'Status':'Loaded' if ok else 'Pending','File':path.name,'Size KB':round(path.stat().st_size/1024,1) if ok else None})
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    st.markdown('#### Current reconciliation coverage')
    st.write(f'**Shopify orders:** {len(ct):,}')
    st.write(f'**Exact matched gateway transactions:** {len(matches):,}')
    st.write(f'**Billed orders:** {(ct["Billing Status"]=="Billed").sum():,}')
    st.write(f'**Orders requiring action:** {(ct["Final Closure"]=="Action Required").sum():,}')
