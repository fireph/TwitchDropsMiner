# Main panel UI components for the WebUI
# Contains the main tab with status, progress, channels, and console output

from typing import TYPE_CHECKING

try:
    from nicegui import ui
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None

if TYPE_CHECKING:
    from webui.manager import WebUIManager


def create_main_panel(manager: 'WebUIManager'):
    """Create the main panel content with status, progress, channels, and console"""
    if not NICEGUI_AVAILABLE:
        return

    with ui.column().classes('w-full gap-2 p-4'):
        # Row 0: Status Bar (full width)
        with ui.card().classes('bg-gray-800 border-gray-700 w-full'):
            ui.label("Status").classes('text-h6 text-white mb-2')
            manager._status_card = ui.label("Initializing...").classes('text-white')

        # Row 1 & 2: Left side (WebSocket, Login on top row; Progress on bottom row) and Right side (Channel List spans both rows)
        with ui.row().classes('w-full gap-2'):
            # Left side: WebSocket/Login on top, Progress below
            with ui.column().classes('flex-1 gap-2'):
                # Top row: WebSocket and Login side by side
                with ui.row().classes('w-full gap-2'):
                    # WebSocket Status
                    with ui.card().classes('bg-gray-800 border-gray-700 flex-1'):
                        ui.label("WebSocket").classes('text-h6 text-white mb-2')
                        with ui.column().classes('gap-1'):
                            manager._ws_status_label = ui.label("Status: Disconnected").classes('text-body2 text-white')
                            manager._ws_topics_label = ui.label("Topics: 0/0").classes('text-body2 text-white')

                    # Login Form
                    with ui.card().classes('bg-gray-800 border-gray-700 flex-1'):
                        ui.label("Login").classes('text-h6 text-white mb-2')
                        with ui.column().classes('gap-1'):
                            ui.label("Please visit the login page").classes('text-body2 text-white')
                            manager._login_status_label = ui.label("Not logged in").classes('text-body2 text-white')
                            ui.button("Login", on_click=lambda: manager.print("Login functionality not implemented in web UI")).classes('bg-blue-600 hover:bg-blue-700 mt-2')

                # Bottom row: Campaign Progress (full width of left side)
                with ui.card().classes('bg-gray-800 border-gray-700 w-full'):
                    ui.label("Campaign Progress").classes('text-h6 text-white mb-2')
                    with ui.column().classes('gap-2'):
                        manager._campaign_name_label = ui.label("No active campaign").classes('text-body1 text-white')
                        manager._game_name_label = ui.label("").classes('text-body2 text-gray-400')
                        manager._progress_bar = ui.linear_progress(value=0).classes('w-full')
                        manager._progress_label = ui.label("0.0%").classes('text-body2 text-white')
                        manager._time_remaining_label = ui.label("").classes('text-body2 text-gray-400')

                # Current Drops section (below progress, left side)
                with ui.card().classes('bg-gray-800 border-gray-700 w-full'):
                    ui.label("Current Drops").classes('text-h6 text-white mb-2')
                    manager._drops_list = ui.column().classes('gap-1')
                    with manager._drops_list:
                        ui.label("No active drops").classes('text-body2 text-gray-400')

            # Right side: Channel List (spans the full height)
            with ui.card().classes('bg-gray-800 border-gray-700 flex-1'):
                ui.label("Channels").classes('text-h6 text-white mb-2')
                manager._channels_list = ui.column().classes('gap-1 h-64 overflow-auto')
                with manager._channels_list:
                    ui.label("No channels loaded").classes('text-body2 text-gray-400')

        # Row 3: Console Output (full width)
        with ui.card().classes('bg-gray-800 border-gray-700 w-full'):
            ui.label("Console Output").classes('text-h6 text-white mb-2')
            manager._console = ui.log(max_lines=50).classes('h-64 bg-gray-900 text-green-400 font-mono text-sm')


def clear_drop(manager: 'WebUIManager'):
    """Clear the current drop display"""
    try:
        if manager._progress_bar is not None:
            manager._progress_bar.set_value(0)
        if manager._progress_label is not None:
            manager._progress_label.set_text("No active drops")
    except Exception as e:
        print(f"Failed to clear drop display: {e}")


def display_drop(manager: 'WebUIManager', drop, *, countdown: bool = True, subone: bool = False):
    """Display current drop information"""
    if drop is None:
        clear_drop(manager)
        return

    try:
        # Update progress if drop has progress information
        if hasattr(drop, 'progress') and manager._progress_bar is not None:
            progress_value = drop.progress / 100.0 if drop.progress <= 100 else drop.progress
            manager._progress_bar.set_value(progress_value)

        if hasattr(drop, 'name') and manager._progress_label is not None:
            manager._progress_label.set_text(f"Mining: {drop.name}")
        elif manager._progress_label is not None:
            manager._progress_label.set_text(f"Mining drop...")
    except Exception as e:
        print(f"Failed to update drop display: {e}")