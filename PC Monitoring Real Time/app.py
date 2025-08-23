import os
import time
import psutil
import threading
from datetime import datetime
from collections import deque
import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html, Input, Output
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# To run this code, you'll need a few more libraries.
# Make sure your virtual environment is active and install them with:
# pip install dash watchdog psutil pandas plotly

# ==================== CONFIGURATION ====================
# Directory to monitor (using os.path.expanduser to handle different OSes)
MONITORED_DIR = os.path.expanduser("~")

# 🔍 FILTERS: Skip temporary files and system-internal junk to reduce noise.
# This makes the log much more useful.
IGNORED_EXTENSIONS = ['.tmp', '.log', '.ldb', '.sqlite', '.dat', '.lock', '.exe']
IGNORED_KEYWORDS = ['AppData\\Local', 'Microsoft\\Edge', 'Windows', 'System32', 'EBWebView', 'CustomDestinations', '.git']
MAX_LOG_ENTRIES = 500
MAX_ALERT_ENTRIES = 100

# ==================== GLOBAL STATE & HELPERS ====================
# Using deque (double-ended queue) for efficient appending and
# memory management, as it automatically discards old entries.
LOGS = deque(maxlen=MAX_LOG_ENTRIES)
ALERTS = deque(maxlen=MAX_ALERT_ENTRIES)
START_TIME = datetime.now()


def current_time():
    """Returns the current time in a formatted string."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def is_relevant_file(path):
    """
    Checks if a file path is relevant for monitoring based on ignored extensions and keywords.
    
    Args:
        path (str): The file path to check.
    
    Returns:
        bool: True if the file is relevant, False otherwise.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in IGNORED_EXTENSIONS:
        return False
    # The any() function is a clean way to check for multiple keywords
    if any(keyword.lower() in path.lower() for keyword in IGNORED_KEYWORDS):
        return False
    return True


def add_log(event_type, message):
    """Adds a new log entry and an alert if the event is significant."""
    log = {"timestamp": current_time(), "type": event_type, "message": message}
    LOGS.append(log)
    if event_type in ["CMD Opened", "File Deleted"]:
        ALERTS.append(log)


# ==================== FILE MONITORING THREAD ====================
class FileMonitorHandler(FileSystemEventHandler):
    """
    Custom event handler for the file system observer.
    This class defines what happens when file events occur.
    """
    def on_deleted(self, event):
        if not event.is_directory and is_relevant_file(event.src_path):
            add_log("File Deleted", f"Deleted: {event.src_path}")

    def on_created(self, event):
        if not event.is_directory and is_relevant_file(event.src_path):
            add_log("File Created", f"Created: {event.src_path}")

    def on_modified(self, event):
        if not event.is_directory and is_relevant_file(event.src_path):
            add_log("File Modified", f"Modified: {event.src_path}")


def start_file_monitor():
    """Sets up and starts the file system observer."""
    observer = Observer()
    observer.schedule(FileMonitorHandler(), MONITORED_DIR, recursive=True)
    observer.start()
    try:
        while observer.is_alive():
            observer.join(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


# ==================== PROCESS MONITORING THREAD ====================
def monitor_cmd():
    """Monitors for new CMD process instances."""
    seen_pids = set()
    while True:
        try:
            for proc in psutil.process_iter(['pid', 'name', 'create_time']):
                if proc.info['name'].lower().startswith('cmd'):
                    ctime = datetime.fromtimestamp(proc.info['create_time'])
                    if ctime >= START_TIME and proc.info['pid'] not in seen_pids:
                        seen_pids.add(proc.info['pid'])
                        add_log("CMD Opened", f"New CMD process detected with PID {proc.info['pid']}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        time.sleep(1)


# ==================== DASHBOARD UI ====================
app = Dash(__name__)
app.title = "SIEM Dashboard"

# Define a consistent style for the dashboard containers
card_style = {
    'backgroundColor': '#2e2e2e',
    'border': '1px solid #444',
    'borderRadius': '8px',
    'padding': '20px',
    'boxShadow': '0 4px 8px rgba(0,0,0,0.2)'
}

# The main layout with key performance indicators and charts
app.layout = html.Div(style={'backgroundColor': "#111111", 'color': '#e0e0e0', 'fontFamily': 'sans-serif', 'padding': '30px'},
    children=[
        html.H1("🛡️ System Activity Monitor", style={'textAlign': 'center', 'color': '#c3e6cb', 'marginBottom': '30px'}),

        # Row for key metrics (KPIs)
        html.Div(style={'display': 'flex', 'justifyContent': 'space-around', 'flexWrap': 'wrap', 'gap': '20px', 'marginBottom': '40px'},
            children=[
                html.Div(id='kpi-uptime', style={**card_style, 'flexGrow': 1, 'textAlign': 'center'}),
                html.Div(id='kpi-total-logs', style={**card_style, 'flexGrow': 1, 'textAlign': 'center'}),
                html.Div(id='kpi-total-alerts', style={**card_style, 'flexGrow': 1, 'textAlign': 'center'}),
            ]),

        # Row for charts
        html.Div(style={'display': 'flex', 'gap': '20px', 'marginBottom': '40px'},
            children=[
                # Events over time line chart
                html.Div([
                    html.H2("Events Over Time", style={'textAlign': 'center', 'color': '#a0d1e1'}),
                    dcc.Graph(id='event-timeline-chart', config={'responsive': False}, style={'height': '300px'})
                ], style={**card_style, 'flex': 2}),

                # Event type breakdown pie chart
                html.Div([
                    html.H2("Event Type Breakdown", style={'textAlign': 'center', 'color': '#a0d1e1'}),
                    dcc.Graph(id='event-type-pie-chart', config={'responsive': False}, style={'height': '300px'})
                ], style={**card_style, 'flex': 1})
            ]),

        # Row for logs and alerts
        html.Div(style={'display': 'flex', 'gap': '20px'},
            children=[
                # Alerts table
                html.Div([
                    html.H2("🚨 Critical Alerts", style={'color': '#f28e8e', 'borderLeft': '4px solid #f28e8e', 'paddingLeft': '10px'}),
                    html.Div(id='alert-output',
                        style={'whiteSpace': 'pre-wrap', 'height': '200px', 'overflowY': 'auto',
                               'border': '1px solid #f28e8e', 'padding': '10px', 'borderRadius': '5px', 'backgroundColor': '#111'})
                ], style={**card_style, 'flex': 1}),

                # All logs table
                html.Div([
                    html.H2("📜 All Activity Logs", style={'color': '#a0d1e1', 'borderLeft': '4px solid #a0d1e1', 'paddingLeft': '10px'}),
                    html.Div(id='log-output',
                        style={'whiteSpace': 'pre-wrap', 'height': '300px', 'overflowY': 'auto',
                               'border': '1px solid #a0d1e1', 'padding': '10px', 'borderRadius': '5px', 'backgroundColor': '#111'})
                ], style={**card_style, 'flex': 2})
            ]),
            
        # This component refreshes the page every 1000ms (1 second)
        dcc.Interval(id='interval', interval=1000, n_intervals=0)
    ])


@app.callback(
    Output('kpi-uptime', 'children'),
    Output('kpi-total-logs', 'children'),
    Output('kpi-total-alerts', 'children'),
    Output('event-timeline-chart', 'figure'),
    Output('event-type-pie-chart', 'figure'),
    Output('alert-output', 'children'),
    Output('log-output', 'children'),
    Input('interval', 'n_intervals')
)
def update_display(n):
    """
    Callback function to update the dashboard display with new data every second.
    It generates the figures for the charts and updates all display elements.
    """
    # Calculate key metrics
    uptime_seconds = (datetime.now() - START_TIME).total_seconds()
    uptime_display = f"<h3>Uptime</h3><p style='font-size:24px; color:#c3e6cb;'>{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m {int(uptime_seconds % 60)}s</p>"
    total_logs_display = f"<h3>Total Logs</h3><p style='font-size:24px; color:#a0d1e1;'>{len(LOGS)}</p>"
    total_alerts_display = f"<h3>Total Alerts</h3><p style='font-size:24px; color:#f28e8e;'>{len(ALERTS)}</p>"

    # Convert logs to a pandas DataFrame for easier plotting
    df = pd.DataFrame(list(LOGS))
    
    # Initialize empty figures if no data exists
    timeline_fig = {}
    pie_fig = {}
    
    if not df.empty:
        # Generate the timeline chart
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['count'] = 1  # Add a count column for aggregation
        timeline_fig = px.line(
            df.resample('1s', on='timestamp').count().reset_index(),
            x='timestamp',
            y='count',
            title='Events Over Time',
            labels={'timestamp': 'Time', 'count': 'Number of Events'},
            template='plotly_dark'
        )
        timeline_fig.update_layout(xaxis_title="Time", yaxis_title="Events/Second", 
                                   paper_bgcolor='#2e2e2e', plot_bgcolor='#2e2e2e', font_color='#e0e0e0')
        timeline_fig.update_traces(line_color='#a0d1e1')

        # Generate the pie chart for event types
        pie_fig = px.pie(
            df,
            names='type',
            title='Event Type Breakdown',
            color_discrete_sequence=px.colors.sequential.Plotly3,
            template='plotly_dark'
        )
        pie_fig.update_layout(paper_bgcolor='#2e2e2e', plot_bgcolor='#2e2e2e', font_color='#e0e0e0')

    # Prepare log and alert text displays
    alert_display = "\n".join(
        [f"[{a['timestamp']}] {a['type']} - {a['message']}" for a in reversed(list(ALERTS))]) or "No alerts yet."
    log_display = "\n".join(
        [f"[{l['timestamp']}] {l['type']} - {l['message']}" for l in reversed(list(LOGS))]) or "No logs yet."

    return (
        uptime_display,
        total_logs_display,
        total_alerts_display,
        timeline_fig,
        pie_fig,
        alert_display,
        log_display
    )


# ==================== MAIN EXECUTION BLOCK ====================
if __name__ == '__main__':
    print(f"✅ Started SIEM Dashboard at {current_time()}")
    # Start the monitoring functions in separate threads to avoid blocking the Dash app
    file_thread = threading.Thread(target=start_file_monitor, daemon=True)
    cmd_thread = threading.Thread(target=monitor_cmd, daemon=True)

    file_thread.start()
    cmd_thread.start()
    
    # Run the Dash web server
    app.run(debug=False, port=8050)
