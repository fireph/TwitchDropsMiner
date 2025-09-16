# Mock classes that provide compatibility with the tkinter GUI interface
# These classes ensure the WebUI can work as a drop-in replacement for the tkinter GUI

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yarl import URL
    from webui.manager import WebUIManager


@dataclass
class LoginData:
    username: str
    password: str
    token: str


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

    def __init__(self, manager: 'WebUIManager'):
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

    def __init__(self, manager: 'WebUIManager'):
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

    def display(self, channel, *, add: bool = False):
        """Display channel in the channels list"""
        pass


class MockInventory:
    """Mock inventory handler for web UI compatibility"""

    def __init__(self, manager):
        self._manager = manager

    def clear(self):
        """Clear inventory"""
        self._manager._campaigns.clear()
        if hasattr(self._manager, '_inventory_container') and self._manager._inventory_container:
            from webui.components.inventory_panel import refresh_inventory_display
            refresh_inventory_display(self._manager)

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

            # Refresh display only if inventory container is available
            if hasattr(self._manager, '_inventory_container') and self._manager._inventory_container:
                from webui.components.inventory_panel import refresh_inventory_display
                refresh_inventory_display(self._manager)

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

    def __init__(self, manager: 'WebUIManager'):
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

    def __init__(self, manager: 'WebUIManager'):
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