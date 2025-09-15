from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

try:
    from nicegui import ui, app
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None
    app = None

from translate import _

if TYPE_CHECKING:
    from twitch import Twitch
    from yarl import URL


@dataclass
class LoginData:
    username: str
    password: str
    token: str


class WebUIManager:
    """
    NiceGUI-based web interface that provides the same interface as GUIManager
    """

    def __init__(self, twitch: Twitch, host: str = "127.0.0.1", port: int = 8080):
        if not NICEGUI_AVAILABLE:
            raise ImportError("NiceGUI is not installed. Install it with: pip install nicegui")

        self._twitch: Twitch = twitch
        self._host = host
        self._port = port
        self._close_requested = asyncio.Event()
        self._running = False
        self._console_log = []

        # Create mock objects for compatibility
        self.tray = MockTray()
        self.status = MockStatus(self)
        self.progress = MockProgress()
        self.output = MockOutput(self)
        self.channels = MockChannels()
        self.inv = MockInventory(self)
        self.login = MockLoginForm(self)
        self.websockets = MockWebsocketStatus()
        self.settings = MockSettings(self)
        self.tabs = MockTabs()

        # Initialize UI components as None - they'll be created when the UI starts
        self._status_label = None
        self._status_card = None
        self._progress_bar = None
        self._progress_label = None
        self._console = None
        self._channels_list = None
        self._drops_list = None
        self._dark_mode_enabled = True  # Track dark mode state

        # Inventory tracking
        self._inventory_filters = {
            "not_linked": False,
            "upcoming": False,
            "active": False,
            "expired": False,
            "excluded": False,
            "finished": False,
        }
        self._campaigns = {}
        self._inventory_container = None

        # Setup the UI page
        self._setup_ui()

        # Setup logging handler
        self._handler = WebUIOutputHandler(self)
        logger = logging.getLogger("TwitchDrops")
        logger.addHandler(self._handler)

        # Start the server in a background task
        self._start_server()

    def _start_server(self):
        """Start the NiceGUI server"""
        import threading
        import time

        def run_server():
            try:
                print(f"Starting NiceGUI server on {self._host}:{self._port}")
                ui.run(
                    host=self._host,
                    port=self._port,
                    title="Twitch Drops Miner",
                    show=False,  # Don't auto-open browser
                    reload=False,
                    favicon="🎮"
                )
            except Exception as e:
                print(f"Failed to start NiceGUI server: {e}")

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # Give the server a moment to start
        time.sleep(1)

    def _setup_ui(self):
        """Setup the NiceGUI interface"""
        # Setup dark theme globally
        ui.dark_mode(True)

        @ui.page('/')
        def index():
            # Set page title and apply dark theme
            ui.page_title("Twitch Drops Miner")

            # Store references to self in the outer scope
            manager = self

            with ui.header().classes('bg-gray-900'):
                ui.label("Twitch Drops Miner").classes('text-h4 text-white')
                ui.space()
                with ui.row():
                    manager._status_label = ui.label("Starting...").classes('text-body1 text-white')
                    ui.button("Stop", on_click=manager.close).classes('bg-red-600 hover:bg-red-700')

            # Create tabbed interface
            with ui.tabs().classes('w-full bg-gray-800') as tabs:
                main_tab = ui.tab("Main", icon="home").classes('text-white')
                settings_tab = ui.tab("Settings", icon="settings").classes('text-white')
                inventory_tab = ui.tab("Inventory", icon="inventory").classes('text-white')

            with ui.tab_panels(tabs, value=main_tab).classes('w-full h-full bg-gray-900'):
                # Main tab content - matching original GUI layout
                with ui.tab_panel(main_tab):
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

                # Settings tab content
                with ui.tab_panel(settings_tab):
                    manager._create_settings_panel()

                # Inventory tab content
                with ui.tab_panel(inventory_tab):
                    manager._create_inventory_panel()

            # Add initial dark mode styling (will be updated by toggle)
            manager._apply_initial_styles()

    def _create_settings_panel(self):
        """Create the settings panel content"""
        with ui.row().classes('w-full gap-4 p-4'):
            # Left column - General settings
            with ui.column().classes('w-1/2'):
                with ui.card().classes('bg-gray-800 border-gray-700'):
                    ui.label("General Settings").classes('text-h6 text-white mb-4')

                    # Language setting
                    with ui.row().classes('items-center gap-4 mb-4'):
                        ui.label("Language 🌐:").classes('text-white w-32')
                        language_select = ui.select(
                            options=['en', 'es', 'fr', 'de', 'pt', 'ru', 'zh'],
                            value='en'
                        ).classes('bg-gray-700 text-white')

                    # Dark mode setting
                    with ui.row().classes('items-center gap-4 mb-4'):
                        ui.label("Dark Mode:").classes('text-white w-32')
                        dark_mode_switch = ui.switch(value=self._dark_mode_enabled, on_change=lambda e: self._toggle_dark_mode(e.value)).classes('text-white')
                        ui.label("(Controls web UI theme)").classes('text-gray-400 text-sm')

                    # Priority mode setting
                    with ui.row().classes('items-center gap-4 mb-4'):
                        ui.label("Priority Mode:").classes('text-white w-32')
                        priority_select = ui.select(
                            options={
                                'priority_only': 'Priority Only',
                                'ending_soonest': 'Ending Soonest',
                                'low_availability': 'Low Availability First'
                            },
                            value='priority_only'
                        ).classes('bg-gray-700 text-white')

                    # Proxy setting
                    with ui.row().classes('items-center gap-4 mb-4'):
                        ui.label("Proxy URL:").classes('text-white w-32')
                        proxy_input = ui.input(
                            placeholder="http://username:password@address:port"
                        ).classes('bg-gray-700 text-white flex-1')

            # Right column - Game exclusions and priority
            with ui.column().classes('w-1/2'):
                with ui.card().classes('bg-gray-800 border-gray-700'):
                    ui.label("Game Management").classes('text-h6 text-white mb-4')

                    # Priority games section
                    with ui.expansion("Priority Games", icon="star").classes('text-white mb-4'):
                        ui.label("Games to prioritize for drops").classes('text-gray-300 mb-2')
                        self._priority_list = ui.column().classes('gap-2')
                        with ui.row().classes('gap-2'):
                            priority_input = ui.input(placeholder="Add game name").classes('bg-gray-700 text-white flex-1')
                            ui.button("Add", on_click=lambda: self._add_priority_game(priority_input.value)).classes('bg-blue-600')

                    # Excluded games section
                    with ui.expansion("Excluded Games", icon="block").classes('text-white'):
                        ui.label("Games to exclude from drops").classes('text-gray-300 mb-2')
                        self._exclude_list = ui.column().classes('gap-2')
                        with ui.row().classes('gap-2'):
                            exclude_input = ui.input(placeholder="Add game name").classes('bg-gray-700 text-white flex-1')
                            ui.button("Add", on_click=lambda: self._add_excluded_game(exclude_input.value)).classes('bg-red-600')

        # Initialize settings values from the actual settings
        if hasattr(self._twitch, 'settings'):
            settings = self._twitch.settings
            try:
                if hasattr(settings, 'language'):
                    language_select.set_value(settings.language)
                if hasattr(settings, 'priority_mode'):
                    priority_mode_map = {
                        'PRIORITY_ONLY': 'priority_only',
                        'ENDING_SOONEST': 'ending_soonest',
                        'LOW_AVBL_FIRST': 'low_availability'
                    }
                    priority_select.set_value(priority_mode_map.get(str(settings.priority_mode), 'priority_only'))
                if hasattr(settings, 'proxy') and settings.proxy:
                    proxy_input.set_value(str(settings.proxy))
                if hasattr(settings, 'dark_mode'):
                    self._dark_mode_enabled = settings.dark_mode
                    dark_mode_switch.set_value(settings.dark_mode)
            except Exception as e:
                print(f"Failed to load settings values: {e}")

        # Add change handlers for settings
        def on_language_change(e):
            if hasattr(self._twitch, 'settings'):
                self._twitch.settings.language = e.value
                self.print(f"Language changed to: {e.value}")

        def on_priority_change(e):
            if hasattr(self._twitch, 'settings'):
                priority_mode_reverse_map = {
                    'priority_only': 'PRIORITY_ONLY',
                    'ending_soonest': 'ENDING_SOONEST',
                    'low_availability': 'LOW_AVBL_FIRST'
                }
                self._twitch.settings.priority_mode = priority_mode_reverse_map.get(e.value, 'PRIORITY_ONLY')
                self.print(f"Priority mode changed to: {e.value}")

        def on_proxy_change(e):
            if hasattr(self._twitch, 'settings'):
                self._twitch.settings.proxy = e.value
                self.print(f"Proxy changed to: {e.value}")

        language_select.on('update:model-value', on_language_change)
        priority_select.on('update:model-value', on_priority_change)
        proxy_input.on('update:model-value', on_proxy_change)

    def _add_priority_game(self, game_name: str):
        """Add a game to the priority list"""
        if game_name and game_name.strip():
            with self._priority_list:
                with ui.row().classes('items-center gap-2'):
                    ui.label(game_name.strip()).classes('text-white flex-1')
                    ui.button("Remove", on_click=lambda: self._remove_priority_game(game_name)).classes('bg-red-600 text-xs')

    def _remove_priority_game(self, game_name: str):
        """Remove a game from the priority list"""
        # In a real implementation, this would remove from the UI and update settings
        pass

    def _add_excluded_game(self, game_name: str):
        """Add a game to the excluded list"""
        if game_name and game_name.strip():
            with self._exclude_list:
                with ui.row().classes('items-center gap-2'):
                    ui.label(game_name.strip()).classes('text-white flex-1')
                    ui.button("Remove", on_click=lambda: self._remove_excluded_game(game_name)).classes('bg-red-600 text-xs')

    def _remove_excluded_game(self, game_name: str):
        """Remove a game from the excluded list"""
        # In a real implementation, this would remove from the UI and update settings
        pass

    def _toggle_dark_mode(self, enabled: bool):
        """Toggle dark mode on/off"""
        self._dark_mode_enabled = enabled

        # Update NiceGUI dark mode
        ui.dark_mode(enabled)

        # Update the CSS dynamically
        if enabled:
            # Apply dark mode styles
            ui.add_head_html('''
                <style id="dark-mode-styles">
                    body, html { background-color: #1f2937 !important; color: #ffffff !important; }
                    .nicegui-content { background-color: #1f2937 !important; color: #ffffff !important; }
                    .q-tab { color: #ffffff !important; }
                    .q-tabs { background-color: #374151 !important; }
                    .q-tab-panels { background-color: #1f2937 !important; color: #ffffff !important; }
                    .q-field__control { background-color: #374151 !important; color: #ffffff !important; }
                    .q-field__native { color: #ffffff !important; }
                    .q-card { background-color: #374151 !important; color: #ffffff !important; }
                    .q-expansion-item { background-color: #374151 !important; color: #ffffff !important; }
                </style>
            ''')
        else:
            # Apply light mode styles
            ui.add_head_html('''
                <style id="light-mode-styles">
                    body, html { background-color: #ffffff !important; color: #000000 !important; }
                    .nicegui-content { background-color: #ffffff !important; color: #000000 !important; }
                    .q-tab { color: #000000 !important; }
                    .q-tabs { background-color: #f3f4f6 !important; }
                    .q-tab-panels { background-color: #ffffff !important; color: #000000 !important; }
                    .q-field__control { background-color: #f9fafb !important; color: #000000 !important; }
                    .q-field__native { color: #000000 !important; }
                    .q-card { background-color: #f9fafb !important; color: #000000 !important; }
                    .q-expansion-item { background-color: #f9fafb !important; color: #000000 !important; }
                </style>
            ''')

        # Print to console for feedback
        mode_text = "dark" if enabled else "light"
        self.print(f"Theme changed to {mode_text} mode")

    def _create_inventory_panel(self):
        """Create the inventory panel content with filters and campaign list"""
        with ui.column().classes('w-full h-full p-4'):
            # Filter section
            with ui.card().classes('bg-gray-800 border-gray-700 mb-4'):
                ui.label("Filters").classes('text-h6 text-white mb-2')
                with ui.row().classes('gap-4 items-center flex-wrap'):
                    ui.label("Show:").classes('text-white')

                    # Create filter checkboxes
                    self._filter_checkboxes = {}

                    # Not Linked filter
                    with ui.row().classes('items-center gap-1'):
                        self._filter_checkboxes["not_linked"] = ui.checkbox(
                            "Not Linked",
                            value=self._inventory_filters["not_linked"],
                            on_change=lambda e: self._update_filter("not_linked", e.value)
                        ).classes('text-white')

                    # Upcoming filter
                    with ui.row().classes('items-center gap-1'):
                        self._filter_checkboxes["upcoming"] = ui.checkbox(
                            "Upcoming",
                            value=self._inventory_filters["upcoming"],
                            on_change=lambda e: self._update_filter("upcoming", e.value)
                        ).classes('text-white')

                    # Active filter
                    with ui.row().classes('items-center gap-1'):
                        self._filter_checkboxes["active"] = ui.checkbox(
                            "Active",
                            value=self._inventory_filters["active"],
                            on_change=lambda e: self._update_filter("active", e.value)
                        ).classes('text-white')

                    # Expired filter
                    with ui.row().classes('items-center gap-1'):
                        self._filter_checkboxes["expired"] = ui.checkbox(
                            "Expired",
                            value=self._inventory_filters["expired"],
                            on_change=lambda e: self._update_filter("expired", e.value)
                        ).classes('text-white')

                    # Excluded filter
                    with ui.row().classes('items-center gap-1'):
                        self._filter_checkboxes["excluded"] = ui.checkbox(
                            "Excluded",
                            value=self._inventory_filters["excluded"],
                            on_change=lambda e: self._update_filter("excluded", e.value)
                        ).classes('text-white')

                    # Finished filter
                    with ui.row().classes('items-center gap-1'):
                        self._filter_checkboxes["finished"] = ui.checkbox(
                            "Finished",
                            value=self._inventory_filters["finished"],
                            on_change=lambda e: self._update_filter("finished", e.value)
                        ).classes('text-white')

                    # Refresh button
                    ui.button("Refresh", on_click=self._refresh_inventory).classes('bg-blue-600 hover:bg-blue-700')

            # Campaign list section
            with ui.card().classes('bg-gray-800 border-gray-700 flex-1'):
                ui.label("Drops Campaigns").classes('text-h6 text-white mb-2')

                # Simple container without scroll area for debugging
                self._inventory_container = ui.column().classes('gap-2 w-full p-2')

                # Add placeholder message
                with self._inventory_container:
                    ui.label("No campaigns loaded. Click Refresh to load drops campaigns.").classes('text-gray-400 text-center p-4')

                # Add a debug test element that should always be visible
                with self._inventory_container:
                    ui.label("DEBUG: This label should always be visible").classes('text-red-500 bg-yellow-300 p-2')

    def _update_filter(self, filter_name: str, value: bool):
        """Update filter state and refresh display"""
        self._inventory_filters[filter_name] = value
        self.print(f"Filter '{filter_name}' set to: {value}")
        self._refresh_inventory_display()

    def _refresh_inventory(self):
        """Refresh the inventory display"""
        self.print("Refreshing inventory...")

        # Load real campaigns from twitch client
        self._campaigns.clear()

        if hasattr(self._twitch, 'inventory') and self._twitch.inventory:
            for campaign in self._twitch.inventory:
                campaign_data = {
                    'name': campaign.name,
                    'game': getattr(campaign.game, 'name', 'Unknown Game'),
                    'status': self._get_campaign_status(campaign),
                    'progress': self._get_campaign_progress(campaign),
                    'time_remaining': self._get_time_remaining(campaign),
                    'campaign_obj': campaign
                }
                self._campaigns[campaign.id] = campaign_data

        self.print(f"Loaded {len(self._campaigns)} real campaigns")
        self._refresh_inventory_display()

    def _get_campaign_status(self, campaign) -> str:
        """Get campaign status like the original GUI"""
        if campaign.active:
            return "Active"
        elif campaign.upcoming:
            return "Upcoming"
        else:
            return "Expired"

    def _get_campaign_progress(self, campaign) -> float:
        """Get campaign progress percentage"""
        # Look for any drops with progress
        for drop in campaign.drops:
            if hasattr(drop, 'current_minutes') and hasattr(drop, 'required_minutes'):
                if drop.required_minutes > 0:
                    return (drop.current_minutes / drop.required_minutes) * 100
        return 0.0

    def _get_time_remaining(self, campaign) -> str:
        """Get formatted time remaining"""
        try:
            if campaign.active and hasattr(campaign, 'ends_at'):
                from datetime import datetime
                import pytz
                now = datetime.now(pytz.UTC)
                time_diff = campaign.ends_at - now
                if time_diff.total_seconds() > 0:
                    days = time_diff.days
                    hours, remainder = divmod(time_diff.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)

                    if days > 0:
                        return f"{days}d {hours}h {minutes}m"
                    elif hours > 0:
                        return f"{hours}h {minutes}m"
                    else:
                        return f"{minutes}m"
            elif campaign.upcoming and hasattr(campaign, 'starts_at'):
                from datetime import datetime
                import pytz
                now = datetime.now(pytz.UTC)
                time_diff = campaign.starts_at - now
                if time_diff.total_seconds() > 0:
                    days = time_diff.days
                    hours, remainder = divmod(time_diff.seconds, 3600)
                    if days > 0:
                        return f"Starts in {days}d {hours}h"
                    else:
                        return f"Starts in {hours}h"
        except Exception as e:
            self.print(f"Error calculating time remaining: {e}")

        return ""


    def _refresh_inventory_display(self):
        """Refresh the display of campaigns based on current filters"""
        if self._inventory_container is None:
            self.print("ERROR: inventory container is None")
            return

        self.print(f"Refreshing display with {len(self._campaigns)} campaigns")
        self.print(f"Inventory container type: {type(self._inventory_container)}")

        try:
            # Clear current display
            self.print("Clearing inventory container...")
            self._inventory_container.clear()
            self.print("Container cleared successfully")

            # Add campaigns based on filters
            if not self._campaigns:
                # Show placeholder if no campaigns
                self.print("No campaigns found, showing placeholder")
                with self._inventory_container:
                    ui.label("No campaigns available. Click Refresh to load test campaigns.").classes('text-gray-400 text-center p-4')
            else:
                # Display filtered campaigns
                shown_count = 0
                for campaign_id, campaign_data in self._campaigns.items():
                    try:
                        if self._should_show_campaign(campaign_data):
                            self.print(f"Adding campaign: {campaign_data.get('name', 'Unknown')}")
                            self._add_campaign_to_display(campaign_data)
                            shown_count += 1
                        else:
                            self.print(f"Filtering out campaign: {campaign_data.get('name', 'Unknown')} (status: {campaign_data.get('status', 'Unknown')})")
                    except Exception as e:
                        self.print(f"Error processing campaign {campaign_id}: {e}")

                self.print(f"Displayed {shown_count} out of {len(self._campaigns)} campaigns")

                if shown_count == 0:
                    self.print("No campaigns passed filters, showing filter message")
                    with self._inventory_container:
                        ui.label("No campaigns match the current filters. Try adjusting the filter checkboxes above.").classes('text-gray-400 text-center p-4')
                else:
                    self.print("Campaigns should now be visible in the UI")

        except Exception as e:
            self.print(f"ERROR in _refresh_inventory_display: {e}")
            # Add emergency debug info
            with self._inventory_container:
                ui.label(f"ERROR: Failed to display campaigns - {str(e)}").classes('text-red-400 p-4')

    def _should_show_campaign(self, campaign_data):
        """Determine if a campaign should be shown based on current filters"""
        campaign = campaign_data.get('campaign_obj')

        # Get filter states
        show_not_linked = self._inventory_filters["not_linked"]
        show_upcoming = self._inventory_filters["upcoming"]
        show_active = self._inventory_filters["active"]
        show_expired = self._inventory_filters["expired"]
        show_excluded = self._inventory_filters["excluded"]
        show_finished = self._inventory_filters["finished"]

        # Check status filters based on campaign data
        status = campaign_data.get('status', '').lower()

        # Debug output
        self.print(f"Checking campaign {campaign_data.get('name', 'Unknown')} with status '{status}'")
        self.print(f"Filters - upcoming: {show_upcoming}, active: {show_active}, expired: {show_expired}, finished: {show_finished}")

        # For test campaigns or campaigns without objects, use simpler logic
        if not campaign:
            # Check if any filters are enabled - if none are enabled, show nothing
            any_filter_enabled = (show_not_linked or show_upcoming or show_active or show_expired or
                                show_excluded or show_finished)

            if not any_filter_enabled:
                return False  # Hide everything when no filters are selected

            # Only show if the corresponding filter is enabled
            if status == 'upcoming':
                return show_upcoming
            elif status == 'active':
                return show_active
            elif status == 'expired':
                return show_expired
            elif status == 'finished':
                return show_finished
            else:
                # Unknown status, don't show
                return False

        # For real campaign objects, use more complex logic
        # Check eligibility (not linked filter)
        eligible = getattr(campaign, 'eligible', True)
        if show_not_linked and not eligible:
            return False  # Don't show not linked if filter is on and it's linked

        if status == 'upcoming':
            return show_upcoming
        elif status == 'active':
            return show_active
        elif status == 'expired':
            return show_expired
        elif status == 'finished':
            return show_finished

        # Check excluded filter
        if hasattr(campaign, 'game') and hasattr(self._twitch, 'settings'):
            game_name = getattr(campaign.game, 'name', '')
            is_excluded = game_name in getattr(self._twitch.settings, 'exclude', set())
            if is_excluded and not show_excluded:
                return False

        return True

    def _add_campaign_to_display(self, campaign_data):
        """Add a campaign to the display"""
        try:
            campaign_name = campaign_data.get('name', 'Unknown Campaign')
            status = campaign_data.get('status', 'Unknown')
            game = campaign_data.get('game', 'Unknown Game')
            progress = campaign_data.get('progress', 0)
            time_remaining = campaign_data.get('time_remaining', '')

            self.print(f"Creating UI for campaign: {campaign_name}")

            # Create a proper campaign card
            with self._inventory_container:
                with ui.card().classes('w-full mb-2 p-4'):
                    with ui.row().classes('w-full items-center gap-4'):
                        # Campaign info
                        with ui.column().classes('flex-grow'):
                            ui.label(campaign_name).classes('text-lg font-bold')
                            ui.label(f"Game: {game}").classes('text-sm text-gray-600')

                            # Status with color coding
                            status_class = 'text-sm font-medium '
                            if status.lower() == 'active':
                                status_class += 'text-green-600'
                            elif status.lower() == 'upcoming':
                                status_class += 'text-blue-600'
                            elif status.lower() == 'expired':
                                status_class += 'text-red-600'
                            elif status.lower() == 'finished':
                                status_class += 'text-purple-600'
                            else:
                                status_class += 'text-gray-600'

                            ui.label(f"Status: {status}").classes(status_class)

                        # Progress info
                        if progress > 0:
                            with ui.column().classes('items-end'):
                                ui.label(f"{progress:.1f}%").classes('text-sm font-medium')
                                if time_remaining:
                                    ui.label(time_remaining).classes('text-xs text-gray-500')

            self.print(f"Successfully added campaign {campaign_name}")

        except Exception as e:
            self.print(f"ERROR adding campaign to display: {e}")
            import traceback
            self.print(f"Traceback: {traceback.format_exc()}")
            # Add fallback display
            try:
                with self._inventory_container:
                    ui.label(f"ERROR: {campaign_data.get('name', 'Unknown')} - {str(e)}").classes('text-red-400 p-2')
            except Exception as e2:
                self.print(f"Even fallback failed: {e2}")

    def _apply_initial_styles(self):
        """Apply initial styling based on current dark mode setting"""
        self._toggle_dark_mode(self._dark_mode_enabled)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    def print(self, message: str):
        """Print message to console output"""
        timestamp = datetime.now().strftime("%X")
        formatted_message = f"{timestamp}: {message}"

        # Store in console log for display
        self._console_log.append(formatted_message)

        # Also print to console if available
        if self._console is not None:
            try:
                if '\n' in message:
                    for line in message.split('\n'):
                        if line.strip():
                            self._console.push(f"{timestamp}: {line}")
                else:
                    self._console.push(formatted_message)
            except Exception as e:
                # Fallback to standard print if UI update fails
                print(f"{formatted_message} (UI update failed: {e})")
        else:
            # Fallback to standard print if UI not ready
            print(formatted_message)

    def close(self, *args) -> int:
        """Request the GUI application to close"""
        self._close_requested.set()
        return 0

    async def wait_until_closed(self):
        """Wait until the user closes the window"""
        await self._close_requested.wait()

    def stop(self):
        """Stop the GUI polling and cleanup"""
        self._running = False

    def close_window(self):
        """Close the window and cleanup"""
        if hasattr(logging.getLogger("TwitchDrops"), 'removeHandler'):
            logging.getLogger("TwitchDrops").removeHandler(self._handler)
        app.shutdown()

    def grab_attention(self, *, sound: bool = True):
        """Grab user attention (web UI equivalent)"""
        # In a web UI, we can't grab attention in the same way
        # But we can update the title or show a notification
        self.print("⚠️  Attention: Application requires user interaction")

    def start(self):
        """Start the web UI"""
        self._running = True

    async def coro_unless_closed(self, coro):
        """Execute coroutine unless the GUI is closed"""
        import asyncio
        from exceptions import ExitRequest

        # In Python 3.11, we need to explicitly wrap awaitables
        tasks = [asyncio.ensure_future(coro), asyncio.ensure_future(self._close_requested.wait())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if self._close_requested.is_set():
            raise ExitRequest()
        return await next(iter(done))

    def clear_drop(self):
        """Clear the current drop display"""
        try:
            if self._progress_bar is not None:
                self._progress_bar.set_value(0)
            if self._progress_label is not None:
                self._progress_label.set_text("No active drops")
        except Exception as e:
            print(f"Failed to clear drop display: {e}")

    def display_drop(self, drop, *, countdown: bool = True, subone: bool = False):
        """Display current drop information"""
        if drop is None:
            self.clear_drop()
            return

        try:
            # Update progress if drop has progress information
            if hasattr(drop, 'progress') and self._progress_bar is not None:
                progress_value = drop.progress / 100.0 if drop.progress <= 100 else drop.progress
                self._progress_bar.set_value(progress_value)

            if hasattr(drop, 'name') and self._progress_label is not None:
                self._progress_label.set_text(f"Mining: {drop.name}")
            elif self._progress_label is not None:
                self._progress_label.set_text(f"Mining drop...")
        except Exception as e:
            print(f"Failed to update drop display: {e}")

    def set_games(self, games) -> None:
        """Set available games (no-op for web UI)"""
        pass

    def apply_theme(self, dark: bool) -> None:
        """Apply theme (no-op for web UI)"""
        pass

    def save(self, *, force: bool = False) -> None:
        """Save GUI state (no-op for web UI)"""
        pass

    def prevent_close(self):
        """Prevent the application from closing (used for error states)"""
        self._close_requested.clear()
        self.print("Application prevented from closing due to error state")


class MockTray:
    """Mock system tray for web UI compatibility"""

    def change_icon(self, icon_name: str):
        """Change tray icon (no-op for web UI)"""
        pass

    def update_title(self, drop):
        """Update tray title (no-op for web UI)"""
        pass

    def restore(self):
        """Restore window from tray (no-op for web UI)"""
        pass

    def stop(self):
        """Stop tray (no-op for web UI)"""
        pass


class MockStatus:
    """Mock status bar for web UI compatibility"""

    def __init__(self, manager: WebUIManager):
        self._manager = manager

    def update(self, text: str):
        """Update status text"""
        try:
            if self._manager._status_card is not None:
                self._manager._status_card.set_text(text)
            if self._manager._status_label is not None:
                self._manager._status_label.set_text(text)
        except Exception as e:
            print(f"Failed to update status: {e}")

    def clear(self):
        """Clear status text"""
        self.update("")


class MockProgress:
    """Mock progress bar for web UI compatibility"""

    def __init__(self):
        self._manager = None

    def stop_timer(self):
        """Stop progress timer"""
        pass

    def display(self, drop, *, countdown: bool = True, subone: bool = False):
        """Display drop progress (no-op for web UI)"""
        pass

    def minute_almost_done(self) -> bool:
        """Check if minute is almost done (always False for web UI)"""
        return False


class MockOutput:
    """Mock output handler for web UI compatibility"""

    def __init__(self, manager: WebUIManager):
        self._manager = manager

    def print(self, message: str):
        """Print to output"""
        self._manager.print(message)


class MockChannels:
    """Mock channels handler for web UI compatibility"""

    def clear(self):
        """Clear channels list"""
        pass

    def set_watching(self, channel):
        """Set watching channel"""
        pass

    def clear_watching(self):
        """Clear watching channel"""
        pass

    def get_selection(self):
        """Get selected channel (returns None for web UI)"""
        return None

    def clear_selection(self):
        """Clear channel selection"""
        pass


class MockInventory:
    """Mock inventory handler for web UI compatibility"""

    def __init__(self, manager):
        self._manager = manager

    def clear(self):
        """Clear inventory"""
        self._manager._campaigns.clear()
        if self._manager._inventory_container:
            self._manager._refresh_inventory_display()

    async def add_campaign(self, campaign):
        """Add campaign to inventory"""
        try:
            # Extract campaign data
            campaign_data = {
                'name': getattr(campaign, 'name', 'Unknown Campaign'),
                'game': getattr(campaign.game, 'name', 'Unknown Game') if hasattr(campaign, 'game') else 'Unknown Game',
                'status': self._get_campaign_status(campaign),
                'progress': getattr(campaign, 'progress', 0),
                'time_remaining': self._get_time_remaining(campaign),
                'campaign_obj': campaign  # Store the actual campaign object
            }

            # Add to campaigns dictionary
            campaign_id = getattr(campaign, 'id', str(len(self._manager._campaigns)))
            self._manager._campaigns[campaign_id] = campaign_data

            # Refresh display
            self._manager._refresh_inventory_display()

            self._manager.print(f"Added campaign: {campaign_data['name']}")
        except Exception as e:
            self._manager.print(f"Failed to add campaign: {e}")

    def _get_campaign_status(self, campaign):
        """Get campaign status text"""
        if hasattr(campaign, 'active') and campaign.active:
            return "Active"
        elif hasattr(campaign, 'upcoming') and campaign.upcoming:
            return "Upcoming"
        elif hasattr(campaign, 'expired') and campaign.expired:
            return "Expired"
        else:
            return "Unknown"

    def _get_time_remaining(self, campaign):
        """Get time remaining text"""
        if hasattr(campaign, 'ends_at') and campaign.ends_at:
            try:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                remaining = campaign.ends_at - now
                if remaining.total_seconds() > 0:
                    days = remaining.days
                    hours, remainder = divmod(remaining.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)

                    if days > 0:
                        return f"{days}d {hours}h {minutes}m"
                    elif hours > 0:
                        return f"{hours}h {minutes}m"
                    else:
                        return f"{minutes}m"
                else:
                    return "Expired"
            except:
                return ""
        return ""

    def configure_theme(self, *, bg: str):
        """Configure theme (no-op for web UI)"""
        pass


class MockLoginForm:
    """Mock login form for web UI compatibility"""

    def __init__(self, manager: WebUIManager):
        self._manager = manager

    def clear(self, login: bool = False, password: bool = False, token: bool = False):
        """Clear login form fields"""
        pass

    async def wait_for_login_press(self) -> None:
        """Wait for login button press (no-op for web UI)"""
        pass

    async def ask_login(self) -> LoginData:
        """Ask for login credentials (placeholder implementation)"""
        self._manager.print("Login required: Please provide credentials via web interface")
        # For now, return dummy credentials - in a real implementation,
        # this would show a login form in the web UI and wait for user input
        return LoginData("", "", "")

    async def ask_enter_code(self, page_url: 'URL', user_code: str) -> None:
        """Ask to enter device activation code"""
        from utils import webopen
        self._manager.print(f"Enter this code on the Twitch's device activation page: {user_code}")
        twitch_login_url = f"https://www.twitch.tv/activate?device-code={user_code}"
        self._manager.print(f"Navigate to: {twitch_login_url}")
        await asyncio.sleep(4)
        webopen(page_url)

    def update(self, status: str, user_id: int | None):
        """Update login status"""
        if user_id is not None:
            user_str = str(user_id)
        else:
            user_str = "-"
        self._manager.print(f"Login status: {status} (User ID: {user_str})")


class MockWebsocketStatus:
    """Mock websocket status handler for web UI compatibility"""

    def __init__(self):
        self._items: dict[int, dict] = {}

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
        """Update websocket status"""
        if status is None and topics is None:
            raise TypeError("You need to provide at least one of: status, topics")

        if idx not in self._items:
            self._items[idx] = {"status": "disconnected", "topics": 0}

        if status is not None:
            self._items[idx]["status"] = status
        if topics is not None:
            self._items[idx]["topics"] = topics

    def remove(self, idx: int):
        """Remove websocket status entry"""
        if idx in self._items:
            del self._items[idx]


class MockSettings:
    """Mock settings panel for web UI compatibility"""

    def __init__(self, manager: WebUIManager):
        self._manager = manager
        # Mock attributes that might be referenced
        self._priority_list = MockList()
        self._exclude_list = MockList()

    def clear_selection(self):
        """Clear settings selection (no-op for web UI)"""
        pass

    def set_games(self, games):
        """Set available games for settings"""
        # Could update the game lists in the UI
        pass


class MockList:
    """Mock list for settings compatibility"""

    def configure_theme(self, **kwargs):
        """Configure theme (no-op for web UI)"""
        pass


class MockTabs:
    """Mock tabs handler for web UI compatibility"""

    def current_tab(self):
        """Get current tab index (returns 0 for main tab)"""
        return 0

    def add_view_event(self, callback):
        """Add view event callback (no-op for web UI)"""
        pass


class WebUIOutputHandler(logging.Handler):
    """Logging handler that outputs to the web UI"""

    def __init__(self, output: WebUIManager):
        super().__init__()
        self._output = output

    def emit(self, record):
        self._output.print(self.format(record))


