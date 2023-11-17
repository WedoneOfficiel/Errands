# Copyright 2023 Vlad Krupinskii <mrvladus@yandex.ru>
# SPDX-License-Identifier: MIT

from errands.utils.animation import scroll
from errands.utils.gsettings import GSettings
from errands.utils.data import UserData
from errands.utils.functions import get_children
from errands.widgets.details import Details
from errands.widgets.trash import Trash
from gi.repository import Adw, Gtk, GLib, Gio
from errands.widgets.task import Task
from errands.utils.markup import Markup
from errands.utils.sync import Sync
from errands.utils.logging import Log


class TasksList(Adw.Bin):
    # State
    scrolling: bool = False  # Is window scrolling
    startup: bool = True

    def __init__(self, window, list_uid: str, parent):
        super().__init__()
        self.window = window
        self.list_uid = list_uid
        self.parent = parent
        self.build_ui()
        self.add_actions()
        self.load_tasks()

    def build_ui(self):
        # Title
        self.title = Adw.WindowTitle(
            title=UserData.run_sql(
                f"SELECT name FROM lists WHERE uid = '{self.list_uid}'",
                fetch=True,
            )[0][0]
        )
        # Delete completed button
        delete_completed_btn = Gtk.Button(
            valign="center",
            icon_name="edit-clear-all-symbolic",
            tooltip_text=_("Delete Completed Tasks"),  # type:ignore
        )
        delete_completed_btn.connect("clicked", self.on_delete_completed_btn_clicked)
        self.delete_completed_btn_rev = Gtk.Revealer(
            child=delete_completed_btn, transition_type=2
        )
        # Scroll up btn
        scroll_up_btn = Gtk.Button(
            valign="center",
            icon_name="go-up-symbolic",
            tooltip_text=_("Scroll Up"),  # type:ignore
        )
        scroll_up_btn.connect("clicked", self.on_scroll_up_btn_clicked)
        self.scroll_up_btn_rev = Gtk.Revealer(child=scroll_up_btn, transition_type=3)
        # Menu
        menu: Gio.Menu = Gio.Menu.new()
        menu.append(_("Edit"), "tasks_list.edit")  # type:ignore
        menu.append(_("Sync/Fetch Tasks"), "tasks_list.sync")  # type:ignore
        menu.append(_("Delete"), "tasks_list.delete")  # type:ignore
        # Header Bar
        hb = Adw.HeaderBar(title_widget=self.title)
        hb.pack_start(self.delete_completed_btn_rev)
        hb.pack_end(self.scroll_up_btn_rev)
        hb.pack_end(
            Gtk.MenuButton(
                menu_model=menu,
                icon_name="view-more-symbolic",
                tooltip_text=_("Menu"),  # type:ignore
            )
        )

        # Entry
        entry = Adw.EntryRow(
            activatable=False,
            height_request=60,
            title=_("Add new Task"),  # type:ignore
        )
        entry.connect("entry-activated", self.on_task_added)
        entry_box = Gtk.ListBox(
            selection_mode=0,
            css_classes=["boxed-list"],
            margin_start=12,
            margin_end=12,
            margin_top=12,
            margin_bottom=12,
        )
        entry_box.append(entry)

        # Srolled window
        adj = Gtk.Adjustment()
        adj.connect("value-changed", self.on_scroll)
        self.scrl = Gtk.ScrolledWindow(
            propagate_natural_height=True, propagate_natural_width=True, vadjustment=adj
        )
        self.dnd_ctrl = Gtk.DropControllerMotion()
        self.dnd_ctrl.connect("motion", self.on_dnd_scroll)
        self.scrl.add_controller(self.dnd_ctrl)

        # Tasks list
        self.tasks_list = Gtk.Box(
            orientation="vertical", hexpand=True, margin_bottom=18
        )
        self.tasks_list.add_css_class("tasks-list")
        self.scrl.set_child(
            Adw.Clamp(maximum_size=850, tightening_threshold=300, child=self.tasks_list)
        )
        # Tasks list box
        box = Gtk.Box(orientation="vertical")
        box.append(
            Adw.Clamp(
                maximum_size=850,
                tightening_threshold=300,
                child=entry_box,
            )
        )
        box.append(self.scrl)
        # Tasks list toolbar view
        tasks_toolbar_view = Adw.ToolbarView(
            content=box, width_request=360, height_request=200
        )
        tasks_toolbar_view.add_top_bar(hb)

        # Sidebar
        self.trash_panel = Trash(self.window, self)
        self.details_panel = Details(self.window, self)
        self.sidebar = Adw.ViewStack()
        self.sidebar.add_titled_with_icon(
            self.trash_panel,
            "trash",
            _("Trash"),  # type:ignore
            "user-trash-symbolic",
        )
        self.sidebar.add_titled_with_icon(
            self.details_panel,
            "details",
            _("Details"),  # type:ignore
            "help-about-symbolic",
        )
        # Sidebar toolbar view
        sidebar_toolbar_view = Adw.ToolbarView(
            content=self.sidebar, width_request=360, height_request=200
        )
        sidebar_toolbar_view.add_bottom_bar(
            Adw.ViewSwitcherBar(stack=self.sidebar, reveal=True)
        )

        # Split view
        split_view = Adw.OverlaySplitView(
            content=tasks_toolbar_view,
            sidebar=sidebar_toolbar_view,
            sidebar_position="start",
        )
        self.set_child(split_view)

    def add_actions(self):
        group = Gio.SimpleActionGroup()
        self.insert_action_group(name="tasks_list", group=group)

        def _create_action(name: str, callback: callable, shortcuts=None) -> None:
            action: Gio.SimpleAction = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            if shortcuts:
                group.set_accels_for_action(f"tasks_list.{name}", shortcuts)
            group.add_action(action)

        def _edit(*args):
            def _confirm():
                self.parent.rename_list(self)

        def _delete(*args):
            def _confirm(_, res):
                if res == "cancel":
                    Log.debug("Deleting list is cancelled")
                    return
                self.parent.delete_list(self)

            dialog = Adw.MessageDialog(
                transient_for=self.window,
                hide_on_close=True,
                heading=_("Are you sure?"),  # type:ignore
                body=_("List will be permanently deleted"),  # type:ignore
                default_response="delete",
                close_response="cancel",
            )
            dialog.add_response("delete", _("Delete"))  # type:ignore
            dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.add_response("cancel", _("Cancel"))  # type:ignore
            dialog.connect("response", _confirm)
            dialog.present()

        _create_action("edit", _edit)
        _create_action("delete", _delete)
        _create_action("sync", lambda *_: Sync.sync(True))

    def add_task(self, uid: str) -> None:
        new_task = Task(uid, self.list_uid, self.window, self, self, False)
        self.tasks_list.append(new_task)
        new_task.toggle_visibility(not new_task.get_prop("deleted"))

    def get_all_tasks(self) -> list[Task]:
        """
        Get list of all tasks widgets including sub-tasks
        """

        tasks: list[Task] = []

        def append_tasks(items: list[Task]) -> None:
            for task in items:
                tasks.append(task)
                children: list[Task] = get_children(task.tasks_list)
                if len(children) > 0:
                    append_tasks(children)

        append_tasks(get_children(self.tasks_list))
        return tasks

    def get_toplevel_tasks(self) -> list[Task]:
        return get_children(self.tasks_list)

    def load_tasks(self) -> None:
        Log.debug(f"Loading tasks for '{self.list_uid}'")
        for uid in UserData.get_toplevel_tasks(self.list_uid):
            self.add_task(uid)
        self.update_status()
        # Expand tasks if needed
        if GSettings.get("expand-on-startup"):
            for task in self.get_all_tasks():
                if len(get_children(task.tasks_list)) > 0:
                    task.expand(True)
        Sync.sync(True)

    def update_status(self) -> None:
        """
        Update status bar on the top
        """

        n_total: int = UserData.run_sql(
            f"""SELECT COUNT(*) FROM tasks
            WHERE parent IS NULL 
            AND deleted = 0
            AND list_uid = '{self.list_uid}'""",
            fetch=True,
        )[0][0]
        n_completed: int = UserData.run_sql(
            f"""SELECT COUNT(*) FROM tasks 
            WHERE parent IS NULL 
            AND completed = 1
            AND deleted = 0
            AND list_uid = '{self.list_uid}'""",
            fetch=True,
        )[0][0]
        n_all_deleted: int = UserData.run_sql(
            f"""SELECT COUNT(*) FROM tasks 
            WHERE deleted = 1 
            AND list_uid = '{self.list_uid}'""",
            fetch=True,
        )[0][0]
        n_all_completed: int = UserData.run_sql(
            f"""SELECT COUNT(*) FROM tasks 
            WHERE completed = 1
            AND deleted = 0 
            AND list_uid = '{self.list_uid}'""",
            fetch=True,
        )[0][0]

        self.title.set_subtitle(
            _("Completed:") + f" {n_completed} / {n_total}"  # type:ignore
            if n_total > 0
            else ""
        )
        self.delete_completed_btn_rev.set_reveal_child(n_all_completed > 0)
        self.trash_panel.scrl.set_visible(n_all_deleted > 0)

    def update_ui(self) -> None:
        Log.debug("Updating UI")

        # Update existing tasks
        tasks: list[Task] = self.get_all_tasks()
        data_tasks = UserData.get()["tasks"]
        to_change_parent = []
        to_remove: list[Task] = []
        for task in tasks:
            for t in data_tasks:
                if task.task["id"] == t["id"]:
                    # If parent is changed
                    if task.task["parent"] != t["parent"]:
                        to_change_parent.append(t)
                        to_remove.append(task)
                        break
                    # If text changed
                    if task.task["text"] != t["text"]:
                        task.task["text"] = t["text"]
                        task.text = Markup.find_url(Markup.escape(task.task["text"]))
                        task.task_row.props.title = task.text
                    # If completion changed
                    if task.task["completed"] != t["completed"]:
                        task.completed_btn.props.active = t["completed"]

        # Remove old tasks
        for task in to_remove:
            task.purge()

        # Change parents
        for task in to_change_parent:
            if task["parent"] == "":
                self.tasks_list.add_task(task)
            else:
                for t in tasks:
                    if t.task["id"] == task["parent"]:
                        t.add_task(task)
                        break

        # Create new tasks
        tasks_ids: list[str] = [
            task.task["id"] for task in self.tasks_list.get_all_tasks()
        ]
        for task in data_tasks:
            if task["id"] not in tasks_ids:
                # Add toplevel task and its sub-tasks
                if task["parent"] == "":
                    self.tasks_list.add_task(task)
                # Add sub-task and its sub-tasks
                else:
                    for t in self.tasks_list.get_all_tasks():
                        if t.task["id"] == task["parent"]:
                            t.add_task(task)
                tasks_ids = [
                    task.task["id"] for task in self.tasks_list.get_all_tasks()
                ]

        # Remove tasks
        ids = [t["id"] for t in UserData.get()["tasks"]]
        for task in self.tasks_list.get_all_tasks():
            if task.task["id"] not in ids:
                task.purge()

    def on_delete_completed_btn_clicked(self, _) -> None:
        """
        Hide completed tasks and move them to trash
        """
        Log.info("Delete completed tasks")

        for task in self.get_all_tasks():
            if task.get_prop("completed") and not task.get_prop("deleted"):
                task.delete()
        self.update_status()

    def on_dnd_scroll(self, _motion, _x, y) -> bool:
        """
        Autoscroll while dragging task
        """

        def _auto_scroll(scroll_up: bool) -> bool:
            """Scroll while drag is near the edge"""
            if not self.scrolling or not self.dnd_ctrl.contains_pointer():
                return False
            adj = self.scrl.get_vadjustment()
            if scroll_up:
                adj.set_value(adj.get_value() - 2)
                return True
            else:
                adj.set_value(adj.get_value() + 2)
                return True

        MARGIN: int = 50
        height: int = self.scrl.get_allocation().height
        if y < MARGIN:
            self.scrolling = True
            GLib.timeout_add(100, _auto_scroll, True)
        elif y > height - MARGIN:
            self.scrolling = True
            GLib.timeout_add(100, _auto_scroll, False)
        else:
            self.scrolling = False

    def on_scroll(self, adj) -> None:
        """
        Show scroll up button
        """

        self.scroll_up_btn_rev.set_reveal_child(adj.get_value() > 0)

    def on_scroll_up_btn_clicked(self, _) -> None:
        """
        Scroll up
        """

        scroll(self.scrl, False)

    def on_task_added(self, entry: Gtk.Entry) -> None:
        """
        Add new task
        """

        text: str = entry.props.text
        # Check for empty string or task exists
        if text.strip(" \n\t") == "":
            return
        # Add new task
        uid = UserData.add_task(self.list_uid, text)
        self.add_task(uid)
        # Clear entry
        entry.props.text = ""
        # Scroll to the end
        scroll(self.scrl, True)
        # Sync
        Sync.sync()

    def on_scroll_up_btn_clicked(self, _) -> None:
        scroll(self.scrl, False)
