# Inventory panel UI components for the WebUI
# Contains the inventory tab with filters and campaign list

from typing import TYPE_CHECKING

try:
    from nicegui import ui
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None

if TYPE_CHECKING:
    from webui.manager import WebUIManager


def create_inventory_panel(manager: 'WebUIManager'):
    """Create the inventory panel content with filters and campaign list"""
    if not NICEGUI_AVAILABLE:
        return

    with ui.column().classes('w-full h-full p-4'):
        # Filter section
        _create_filter_section(manager)

        # Campaign list section
        _create_campaign_list_section(manager)


def _create_filter_section(manager: 'WebUIManager'):
    """Create the filter controls section"""
    with ui.card().classes('bg-gray-800 border-gray-700 mb-4'):
        ui.label("Filters").classes('text-h6 text-white mb-2')
        with ui.row().classes('gap-4 items-center flex-wrap'):
            ui.label("Show:").classes('text-white')

            # Create filter checkboxes
            manager._filter_checkboxes = {}

            # Not Linked filter
            with ui.row().classes('items-center gap-1'):
                manager._filter_checkboxes["not_linked"] = ui.checkbox(
                    "Not Linked",
                    value=manager._inventory_filters["not_linked"],
                    on_change=lambda e: update_filter(manager, "not_linked", e.value)
                ).classes('text-white')

            # Upcoming filter
            with ui.row().classes('items-center gap-1'):
                manager._filter_checkboxes["upcoming"] = ui.checkbox(
                    "Upcoming",
                    value=manager._inventory_filters["upcoming"],
                    on_change=lambda e: update_filter(manager, "upcoming", e.value)
                ).classes('text-white')

            # Active filter
            with ui.row().classes('items-center gap-1'):
                manager._filter_checkboxes["active"] = ui.checkbox(
                    "Active",
                    value=manager._inventory_filters["active"],
                    on_change=lambda e: update_filter(manager, "active", e.value)
                ).classes('text-white')

            # Expired filter
            with ui.row().classes('items-center gap-1'):
                manager._filter_checkboxes["expired"] = ui.checkbox(
                    "Expired",
                    value=manager._inventory_filters["expired"],
                    on_change=lambda e: update_filter(manager, "expired", e.value)
                ).classes('text-white')

            # Excluded filter
            with ui.row().classes('items-center gap-1'):
                manager._filter_checkboxes["excluded"] = ui.checkbox(
                    "Excluded",
                    value=manager._inventory_filters["excluded"],
                    on_change=lambda e: update_filter(manager, "excluded", e.value)
                ).classes('text-white')

            # Finished filter
            with ui.row().classes('items-center gap-1'):
                manager._filter_checkboxes["finished"] = ui.checkbox(
                    "Finished",
                    value=manager._inventory_filters["finished"],
                    on_change=lambda e: update_filter(manager, "finished", e.value)
                ).classes('text-white')

            # Refresh button
            ui.button("Refresh", on_click=lambda: refresh_inventory(manager)).classes('bg-blue-600 hover:bg-blue-700')


def _create_campaign_list_section(manager: 'WebUIManager'):
    """Create the campaign list display section"""
    with ui.card().classes('bg-gray-800 border-gray-700 flex-1'):
        ui.label("Drops Campaigns").classes('text-h6 text-white mb-2')

        # Simple container without scroll area for debugging
        manager._inventory_container = ui.column().classes('gap-2 w-full p-2')

        # Add placeholder message
        with manager._inventory_container:
            ui.label("No campaigns loaded. Click Refresh to load drops campaigns.").classes('text-gray-400 text-center p-4')

        # Add a debug test element that should always be visible
        with manager._inventory_container:
            ui.label("DEBUG: This label should always be visible").classes('text-red-500 bg-yellow-300 p-2')


def add_campaign_to_display(manager: 'WebUIManager', campaign_data: dict):
    """Add a campaign to the display"""
    if not NICEGUI_AVAILABLE:
        return

    try:
        campaign_name = campaign_data.get('name', 'Unknown Campaign')
        status = campaign_data.get('status', 'Unknown')
        game = campaign_data.get('game', 'Unknown Game')
        progress = campaign_data.get('progress', 0)
        time_remaining = campaign_data.get('time_remaining', '')

        manager.print(f"Creating UI for campaign: {campaign_name}")

        # Create a proper campaign card
        with manager._inventory_container:
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

        manager.print(f"Successfully added campaign {campaign_name}")

    except Exception as e:
        manager.print(f"ERROR adding campaign to display: {e}")
        import traceback
        manager.print(f"Traceback: {traceback.format_exc()}")
        # Add fallback display
        try:
            with manager._inventory_container:
                ui.label(f"ERROR: {campaign_data.get('name', 'Unknown')} - {str(e)}").classes('text-red-400 p-2')
        except Exception as e2:
            manager.print(f"Even fallback failed: {e2}")


def refresh_inventory(manager: 'WebUIManager'):
    """Refresh the inventory display"""
    from webui.utils import get_campaign_status, get_campaign_progress, format_time_remaining

    manager.print("Refreshing inventory...")

    # Load real campaigns from twitch client
    manager._campaigns.clear()

    if hasattr(manager._twitch, 'inventory') and manager._twitch.inventory:
        for campaign in manager._twitch.inventory:
            campaign_data = {
                'name': campaign.name,
                'game': getattr(campaign.game, 'name', 'Unknown Game'),
                'status': get_campaign_status(campaign),
                'progress': get_campaign_progress(campaign),
                'time_remaining': format_time_remaining(campaign),
                'campaign_obj': campaign
            }
            manager._campaigns[campaign.id] = campaign_data

    manager.print(f"Loaded {len(manager._campaigns)} real campaigns")
    refresh_inventory_display(manager)


def refresh_inventory_display(manager: 'WebUIManager'):
    """Refresh the display of campaigns based on current filters"""
    from webui.utils import should_show_campaign_with_filters

    if not hasattr(manager, '_inventory_container') or manager._inventory_container is None:
        manager.print("DEBUG: inventory container not yet initialized, skipping display refresh")
        return

    manager.print(f"Refreshing display with {len(manager._campaigns)} campaigns")
    manager.print(f"Inventory container type: {type(manager._inventory_container)}")

    try:
        # Clear current display
        manager.print("Clearing inventory container...")
        manager._inventory_container.clear()
        manager.print("Container cleared successfully")

        # Add campaigns based on filters
        if not manager._campaigns:
            # Show placeholder if no campaigns
            manager.print("No campaigns found, showing placeholder")
            with manager._inventory_container:
                ui.label("No campaigns available. Click Refresh to load test campaigns.").classes('text-gray-400 text-center p-4')
        else:
            # Display filtered campaigns
            shown_count = 0
            for campaign_id, campaign_data in manager._campaigns.items():
                try:
                    if should_show_campaign_with_filters(campaign_data, manager._inventory_filters):
                        manager.print(f"Adding campaign: {campaign_data.get('name', 'Unknown')}")
                        add_campaign_to_display(manager, campaign_data)
                        shown_count += 1
                    else:
                        manager.print(f"Filtering out campaign: {campaign_data.get('name', 'Unknown')} (status: {campaign_data.get('status', 'Unknown')})")
                except Exception as e:
                    manager.print(f"Error processing campaign {campaign_id}: {e}")

            manager.print(f"Displayed {shown_count} out of {len(manager._campaigns)} campaigns")

            if shown_count == 0:
                manager.print("No campaigns passed filters, showing filter message")
                with manager._inventory_container:
                    ui.label("No campaigns match the current filters. Try adjusting the filter checkboxes above.").classes('text-gray-400 text-center p-4')
            else:
                manager.print("Campaigns should now be visible in the UI")

    except Exception as e:
        manager.print(f"ERROR in refresh_inventory_display: {e}")
        # Add emergency debug info
        with manager._inventory_container:
            ui.label(f"ERROR: Failed to display campaigns - {str(e)}").classes('text-red-400 p-4')


def update_filter(manager: 'WebUIManager', filter_name: str, value: bool):
    """Update filter state and refresh display"""
    manager._inventory_filters[filter_name] = value
    manager.print(f"Filter '{filter_name}' set to: {value}")
    refresh_inventory_display(manager)