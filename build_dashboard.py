"""
Collections Dashboard — Brio Management
Genera dist/index.html con datos live de NLS SQL Server.
GitHub Actions lo corre cada hora y publica en GitHub Pages.
"""

import os, json
from datetime import datetime
import pyodbc

# ── Conexion NLS ──────────────────────────────────────────────────────────────
NLS_CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=rs3.nortridgehosting.com;"
    "DATABASE=Brio_Management;"
    "UID=Bmrs8800;"
    f"PWD={os.environ.get('NLS_PWD', '!04#c@d629')};"
    "TrustServerCertificate=yes;"
)

# ── Objetivos mensuales ───────────────────────────────────────────────────────
# Para agregar un mes nuevo: una sola linea al final del dict
# (yyyy, m): (target_1, target_2, target_3)  -- target_3=None si no aplica
TARGETS = {
    (2025,  7): (260000, 270600,    None),
    (2025,  8): (275200, 283000,  301400),
    (2025,  9): (274600, 281900,  300500),
    (2025, 10): (323100, 333500,  357500),
    (2025, 11): (319800, 329500,  352200),
    (2025, 12): (302900, 312200,  334600),
    (2026,  1): (302700, 311800,  334100),
    (2026,  2): (282900, 291600,  312700),
    (2026,  3): (274100, 282900,  299600),
    (2026,  4): (285700, 295400,  313100),
    (2026,  5): (279600, 290100,  306800),
}

# ── Constantes SQL ────────────────────────────────────────────────────────────
ALL_CODES = (
    200,201,202,203,204,205,206,207,208,209,210,211,220,221,222,223,
    250,251,280,281,508,509,512,513,524,525,534,535,544,545
)
CODES_STR = ','.join(str(c) for c in ALL_CODES)
OBJ_CODES = '202,203,206,207,210,211,222,223,508,509,534,535,544,545'

CONCEPT_CASE = """CASE
    WHEN transaction_code IN (200,201,204,205,208,209,220,221) THEN 'Principal'
    WHEN transaction_code IN (202,203,206,207,210,211,222,223) THEN 'Interest'
    WHEN transaction_code IN (250,251)                         THEN 'Late Fees'
    WHEN transaction_code IN (508,509)                         THEN 'CPI'
    WHEN transaction_code IN (544,545)                         THEN 'CPI Berkshire'
    WHEN transaction_code IN (534,535)                         THEN 'Lenderin'
    WHEN transaction_code IN (512,513)                         THEN 'Repo'
    WHEN transaction_code IN (280,281,524,525)                 THEN 'Misc Fees'
  END"""

NET_CASE = """CASE
    WHEN transaction_code IN (200,202,204,206,208,210,220,222,250,508,512,524,534,544)
         THEN  transaction_amount
    WHEN transaction_code IN (201,203,205,207,209,211,221,223,251,509,513,525,535,545)
         THEN -transaction_amount
    ELSE 0 END"""

OBJ_CASE = """CASE
    WHEN transaction_code IN (202,206,210,222,508,544,534) THEN  transaction_amount
    WHEN transaction_code IN (203,207,211,223,509,545,535) THEN -transaction_amount
    ELSE 0 END"""

# ── Queries ───────────────────────────────────────────────────────────────────

def q_collections(cur, date_filter):
    cur.execute(f"""
        WITH b AS (SELECT {CONCEPT_CASE} c, {NET_CASE} a
                   FROM loanacct_trans_history
                   WHERE transaction_code IN ({CODES_STR}) AND {date_filter})
        SELECT c, SUM(a) FROM b WHERE c IS NOT NULL GROUP BY c ORDER BY SUM(a) DESC
    """)
    return [(r[0], float(r[1])) for r in cur.fetchall()]


def q_objective(cur, date_filter):
    cur.execute(f"""
        SELECT ISNULL(SUM({OBJ_CASE}),0)
        FROM loanacct_trans_history
        WHERE transaction_code IN ({OBJ_CODES}) AND {date_filter}
    """)
    return float(cur.fetchone()[0])


def q_historical(cur):
    cur.execute(f"""
        WITH b AS (
          SELECT YEAR(transaction_date) yy, MONTH(transaction_date) mm,
                 {OBJ_CASE} obj, {NET_CASE} tot
          FROM loanacct_trans_history
          WHERE transaction_code IN ({CODES_STR})
            AND transaction_date >= DATEADD(MONTH,-11,
                  DATEADD(DAY,1-DAY(GETDATE()),CAST(GETDATE() AS DATE)))
        )
        SELECT yy, mm, ISNULL(SUM(obj),0), ISNULL(SUM(tot),0)
        FROM b GROUP BY yy, mm ORDER BY yy, mm
    """)
    rows = []
    for r in cur.fetchall():
        yy, mm = int(r[0]), int(r[1])
        obj = float(r[2])
        tot = float(r[3])
        t = TARGETS.get((yy, mm), (None, None, None))
        t1, t2, t3 = t
        status = _status(obj, t1, t2, t3)
        pct1 = round(obj / t1 * 100, 1) if t1 else None
        rows.append({
            'label': f"{mm:02d}/{yy}", 'yy': yy, 'mm': mm,
            'obj': obj, 'tot': tot,
            't1': t1, 't2': t2, 't3': t3,
            'status': status, 'pct1': pct1
        })
    return rows


def q_payments(cur):
    cur.execute(f"""
        SELECT TOP 2000
          CONVERT(varchar,CONVERT(date,h.transaction_date),101),
          l.loan_number, l.name,
          {CONCEPT_CASE},
          CASE WHEN h.transaction_code IN (201,203,205,207,209,211,221,223,251,509,513,525,535,545)
               THEN 1 ELSE 0 END,
          {NET_CASE},
          ISNULL(h.user_reference,'')
        FROM loanacct_trans_history h
        JOIN loanacct l ON l.acctrefno = h.acctrefno
        WHERE h.transaction_code IN ({CODES_STR})
          AND DATEPART(mm,h.transaction_date)=DATEPART(mm,GETDATE())
          AND DATEPART(yy,h.transaction_date)=DATEPART(yy,GETDATE())
        ORDER BY h.transaction_date DESC
    """)
    return [{'f':r[0],'ln':str(r[1]),'b':r[2],
             't':r[3] or 'Other','rev':bool(r[4]),
             'a':float(r[5]),'c':r[6]} for r in cur.fetchall()]


def _status(obj, t1, t2, t3):
    if t1 is None: return 'N/A'
    if t3 and obj >= t3: return '3 ALCANZADO'
    if t2 and obj >= t2: return '2 ALCANZADO'
    if obj >= t1:        return '1 ALCANZADO'
    return 'POR DEBAJO'

def _fmt(v):
    return '—' if v is None else f"${v:,.0f}"

def _pct(v, t):
    return min(round(v / t * 100, 1), 999) if t and t > 0 else 0

def _badge(s):
    return {'3 ALCANZADO':'success','2 ALCANZADO':'info',
            '1 ALCANZADO':'warning','POR DEBAJO':'danger','N/A':'secondary'}.get(s,'secondary')

# ── HTML ──────────────────────────────────────────────────────────────────────

def generate_html(data):
    now    = data['now']
    today  = data['today']
    mtd    = data['mtd']
    obj_t  = data['obj_today']
    obj_m  = data['obj_mtd']
    hist   = data['hist']
    pays   = data['payments']

    tot_today = sum(v for _, v in today)
    tot_mtd   = sum(v for _, v in mtd)

    cur_t = TARGETS.get((now.year, now.month), (None, None, None))
    t1, t2, t3 = cur_t
    cur_status = _status(obj_m, t1, t2, t3)
    pct1 = _pct(obj_m, t1)
    pct2 = _pct(obj_m, t2)
    pct3 = _pct(obj_m, t3) if t3 else None

    # ── Chart datasets ────────────────────────────────────────────────────────
    COLORS = ['#1F4E79','#2E75B6','#70AD47','#C55A11','#7F7F7F','#ED7D31','#4472C4','#A9D18E']

    def js_chart_bar(elem_id, labels, values, colors=None):
        if colors is None:
            colors = [COLORS[i % len(COLORS)] for i in range(len(labels))]
        l = json.dumps(labels)
        v = json.dumps(values)
        c = json.dumps(colors)
        return f"""
        new Chart(document.getElementById('{elem_id}'), {{
          type: 'bar',
          data: {{
            labels: {l},
            datasets: [{{
              data: {v},
              backgroundColor: {c},
              borderRadius: 4,
              borderSkipped: false
            }}]
          }},
          options: {{
            responsive: true, maintainAspectRatio: false,
            plugins: {{ legend: {{ display: false }},
              tooltip: {{ callbacks: {{ label: ctx => ' $' + ctx.raw.toLocaleString('en-US',{{minimumFractionDigits:2,maximumFractionDigits:2}}) }} }} }},
            scales: {{ y: {{ ticks: {{ callback: v => '$'+v.toLocaleString('en-US') }} }} }}
          }}
        }});"""

    # Historical combo chart
    hist_labels = json.dumps([h['label'] for h in hist])
    hist_obj    = json.dumps([h['obj']   for h in hist])
    hist_tot    = json.dumps([h['tot']   for h in hist])
    hist_t1     = json.dumps([h['t1']    for h in hist])

    # MTD vs targets
    vt_labels = ['Objetivo MTD']
    vt_vals   = [obj_m]
    vt_colors = ['#2E75B6']
    if t1: vt_labels.append('Target 1'); vt_vals.append(t1); vt_colors.append('#70AD47')
    if t2: vt_labels.append('Target 2'); vt_vals.append(t2); vt_colors.append('#FFC000')
    if t3: vt_labels.append('Target 3'); vt_vals.append(t3); vt_colors.append('#FF5C5C')

    # Payment rows
    pay_rows = ''
    for p in pays:
        cls = ' class="table-danger"' if p['rev'] else ''
        tag = '<span class="badge bg-danger me-1">REV</span>' if p['rev'] else ''
        srch = f"{p['f']} {p['ln']} {p['b']} {p['t']} {p['c']}".lower().replace('"', '')
        pay_rows += f"""
        <tr{cls} data-search="{srch}">
          <td>{p['f']}</td><td>{p['ln']}</td>
          <td>{p['b']}</td>
          <td>{tag}{p['t']}</td>
          <td class="text-end fw-bold">${p['a']:,.2f}</td>
          <td>{p['c']}</td>
        </tr>"""

    # Historical table rows (newest first)
    hist_rows = ''
    for h in reversed(hist):
        sc   = _badge(h['status'])
        pct_str = f"{h['pct1']}%" if h['pct1'] is not None else '—'
        hist_rows += f"""
        <tr>
          <td><b>{h['label']}</b></td>
          <td class="text-end">{_fmt(h['obj'])}</td>
          <td class="text-end text-muted">{_fmt(h['tot'])}</td>
          <td class="text-end">{_fmt(h['t1'])}</td>
          <td class="text-end">{_fmt(h['t2'])}</td>
          <td class="text-end">{_fmt(h['t3'])}</td>
          <td><span class="badge bg-{sc}">{h['status']}</span></td>
          <td class="text-end">{pct_str}</td>
        </tr>"""

    # Progress bar widths (capped at 100% for display)
    pb1 = min(pct1, 100)
    pb2 = min(pct2, 100)
    pb3 = min(pct3, 100) if pct3 is not None else 0
    pb1_col = 'bg-danger' if pct1 < 70 else ('bg-warning' if pct1 < 100 else 'bg-success')
    pb2_col = 'bg-danger' if pct2 < 70 else ('bg-warning' if pct2 < 100 else 'bg-success')

    status_badge_class = _badge(cur_status)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="1800">
  <title>Collections — Brio Management</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <style>
    body {{ background:#f0f4f8; font-family:'Segoe UI',Arial,sans-serif; }}
    .topbar {{ background:linear-gradient(135deg,#1F3864,#2E75B6); color:#fff; padding:16px 28px 14px; }}
    .topbar h1 {{ font-size:1.4rem; font-weight:700; margin:0; letter-spacing:.3px; }}
    .topbar small {{ opacity:.8; font-size:.82rem; }}
    .card {{ border:none; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,.07); }}
    .kpi-val {{ font-size:2rem; font-weight:700; color:#1F3864; line-height:1.1; }}
    .kpi-label {{ font-size:.78rem; text-transform:uppercase; letter-spacing:.5px; color:#6c757d; }}
    .section-title {{ font-size:.85rem; font-weight:600; text-transform:uppercase;
                      letter-spacing:.6px; color:#1F3864; border-left:3px solid #2E75B6;
                      padding-left:8px; margin-bottom:12px; }}
    .chart-wrap {{ position:relative; height:260px; }}
    .chart-wrap-lg {{ position:relative; height:300px; }}
    #pay-search {{ max-width:320px; }}
    .table th {{ font-size:.78rem; text-transform:uppercase; letter-spacing:.4px; }}
    .table td {{ font-size:.85rem; vertical-align:middle; }}
    .progress {{ height:22px; border-radius:6px; }}
    .progress-bar {{ font-size:.78rem; font-weight:600; }}
  </style>
</head>
<body>

<!-- Header -->
<div class="topbar d-flex justify-content-between align-items-center">
  <div>
    <h1>Brio Management &mdash; Collections Dashboard</h1>
    <small>Actualizado: {now.strftime('%d/%m/%Y %H:%M')} ET &nbsp;&bull;&nbsp; Se refresca automaticamente cada hora</small>
  </div>
  <span class="badge bg-{status_badge_class} fs-6 px-3 py-2">{cur_status} &mdash; {now.strftime('%b %Y')}</span>
</div>

<div class="container-fluid px-4 py-3">

  <!-- KPI Cards -->
  <div class="row g-3 mb-3">
    <div class="col-6 col-md-3">
      <div class="card p-3 h-100">
        <div class="kpi-label">Objetivo Hoy</div>
        <div class="kpi-val text-primary">{_fmt(obj_t)}</div>
        <small class="text-muted">Interest + CPI + Lenderin</small>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card p-3 h-100">
        <div class="kpi-label">Objetivo MTD</div>
        <div class="kpi-val text-success">{_fmt(obj_m)}</div>
        <small class="text-muted">Interest + CPI + Lenderin</small>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card p-3 h-100">
        <div class="kpi-label">Total Colectado Hoy</div>
        <div class="kpi-val">{_fmt(tot_today)}</div>
        <small class="text-muted">Todos los conceptos</small>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card p-3 h-100">
        <div class="kpi-label">Total Colectado MTD</div>
        <div class="kpi-val">{_fmt(tot_mtd)}</div>
        <small class="text-muted">Todos los conceptos</small>
      </div>
    </div>
  </div>

  <!-- Progress vs Targets -->
  <div class="card p-3 mb-3">
    <div class="section-title">Progreso del Mes &mdash; {now.strftime('%B %Y')}</div>
    <div class="row align-items-center">
      <div class="col-md-5 mb-3 mb-md-0">
        <div class="chart-wrap">
          <canvas id="chartTargets"></canvas>
        </div>
      </div>
      <div class="col-md-7">
        <div class="mb-3">
          <div class="d-flex justify-content-between mb-1">
            <span class="fw-semibold">Target 1&deg; &mdash; {_fmt(t1)}</span>
            <span class="fw-bold">{pct1}%</span>
          </div>
          <div class="progress">
            <div class="progress-bar {pb1_col}" style="width:{pb1}%">{_fmt(obj_m)}</div>
          </div>
        </div>
        <div class="mb-3">
          <div class="d-flex justify-content-between mb-1">
            <span class="fw-semibold">Target 2&deg; &mdash; {_fmt(t2)}</span>
            <span class="fw-bold">{pct2}%</span>
          </div>
          <div class="progress">
            <div class="progress-bar {pb2_col}" style="width:{pb2}%">{_fmt(obj_m)}</div>
          </div>
        </div>
        {'<div class="mb-3"><div class="d-flex justify-content-between mb-1"><span class="fw-semibold">Target 3&deg; &mdash; '+_fmt(t3)+'</span><span class="fw-bold">'+str(pct3)+'%</span></div><div class="progress"><div class="progress-bar bg-info" style="width:'+str(pb3)+'%">'+_fmt(obj_m)+'</div></div></div>' if t3 else ''}
        <div class="mt-2">
          <small class="text-muted">Objetivo: Interest + CPI + CPI Berkshire + Lenderin (neto de reversals)</small>
        </div>
      </div>
    </div>
  </div>

  <!-- Charts hoy y mes -->
  <div class="row g-3 mb-3">
    <div class="col-md-6">
      <div class="card p-3 h-100">
        <div class="section-title">Colecciones Hoy &mdash; {now.strftime('%d/%m/%Y')}</div>
        <div class="chart-wrap"><canvas id="chartHoy"></canvas></div>
      </div>
    </div>
    <div class="col-md-6">
      <div class="card p-3 h-100">
        <div class="section-title">Colecciones MTD &mdash; {now.strftime('%B %Y')}</div>
        <div class="chart-wrap"><canvas id="chartMtd"></canvas></div>
      </div>
    </div>
  </div>

  <!-- Historical chart -->
  <div class="card p-3 mb-3">
    <div class="section-title">Historico Objetivo &mdash; Ultimos 12 Meses</div>
    <div class="chart-wrap-lg"><canvas id="chartHist"></canvas></div>
  </div>

  <!-- Historical table -->
  <div class="card p-3 mb-3">
    <div class="section-title">Historico con Objetivos</div>
    <div class="table-responsive">
      <table class="table table-sm table-hover align-middle">
        <thead class="table-dark">
          <tr>
            <th>Mes</th>
            <th class="text-end">Objetivo Colectado</th>
            <th class="text-end">Total Colectado</th>
            <th class="text-end">Target 1&deg;</th>
            <th class="text-end">Target 2&deg;</th>
            <th class="text-end">Target 3&deg;</th>
            <th>Status</th>
            <th class="text-end">% vs T1</th>
          </tr>
        </thead>
        <tbody>{hist_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- Payment detail table -->
  <div class="card p-3 mb-4">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <div class="section-title mb-0">Detalle Pagos &mdash; {now.strftime('%B %Y')}</div>
      <input id="pay-search" type="text" class="form-control form-control-sm"
             placeholder="Buscar por loan, nombre, tipo..." oninput="filterTable(this.value)">
    </div>
    <div class="table-responsive" style="max-height:500px;overflow-y:auto">
      <table class="table table-sm table-hover align-middle" id="pay-table">
        <thead class="table-dark sticky-top">
          <tr>
            <th>Fecha</th><th>Loan #</th><th>Deudor</th>
            <th>Tipo</th><th class="text-end">Monto</th><th>Collector</th>
          </tr>
        </thead>
        <tbody id="pay-body">{pay_rows}</tbody>
      </table>
    </div>
    <small class="text-muted mt-1 d-block">Mostrando hasta 2,000 transacciones del mes corriente</small>
  </div>

</div><!-- /container -->

<script>
// ── Charts ────────────────────────────────────────────────────────────────────
{js_chart_bar('chartHoy',
    [c[0] for c in today],
    [c[1] for c in today]
)}

{js_chart_bar('chartMtd',
    [c[0] for c in mtd],
    [c[1] for c in mtd]
)}

{js_chart_bar('chartTargets', vt_labels, vt_vals, vt_colors)}

// Historical combo
new Chart(document.getElementById('chartHist'), {{
  data: {{
    labels: {hist_labels},
    datasets: [
      {{
        type: 'bar',
        label: 'Objetivo Colectado',
        data: {hist_obj},
        backgroundColor: '#2E75B6',
        borderRadius: 4,
        order: 2
      }},
      {{
        type: 'line',
        label: 'Target 1',
        data: {hist_t1},
        borderColor: '#70AD47',
        backgroundColor: 'rgba(112,173,71,.15)',
        pointRadius: 4,
        tension: .3,
        fill: false,
        order: 1
      }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: 'top' }},
      tooltip: {{ callbacks: {{ label: ctx => ' $' + (ctx.raw||0).toLocaleString('en-US',{{minimumFractionDigits:0}}) }} }}
    }},
    scales: {{ y: {{ ticks: {{ callback: v => '$'+v.toLocaleString('en-US') }} }} }}
  }}
}});

// ── Payment table search ──────────────────────────────────────────────────────
function filterTable(q) {{
  q = q.toLowerCase();
  document.querySelectorAll('#pay-body tr').forEach(tr => {{
    tr.style.display = tr.dataset.search && tr.dataset.search.includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Conectando a NLS...")
    conn = pyodbc.connect(NLS_CONN)
    cur  = conn.cursor()

    now = datetime.now()
    today_f = "CONVERT(date,transaction_date) = CONVERT(date,GETDATE())"
    mtd_f   = ("DATEPART(mm,transaction_date)=DATEPART(mm,GETDATE()) "
               "AND DATEPART(yy,transaction_date)=DATEPART(yy,GETDATE())")

    print("Consultando datos...")
    data = {
        'now':       now,
        'today':     q_collections(cur, today_f),
        'mtd':       q_collections(cur, mtd_f),
        'obj_today': q_objective(cur, today_f),
        'obj_mtd':   q_objective(cur, mtd_f),
        'hist':      q_historical(cur),
        'payments':  q_payments(cur),
    }
    conn.close()

    print("Generando HTML...")
    html = generate_html(data)

    os.makedirs('docs', exist_ok=True)
    with open('docs/index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"docs/index.html generado — {len(html):,} bytes")


if __name__ == '__main__':
    main()
