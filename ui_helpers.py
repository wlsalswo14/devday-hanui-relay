"""Operate the real responsive navigation used by browser checks."""
def open_menu(page):
    if page.viewport_size["width"] <= 700:
        if not page.locator("body").evaluate("e=>e.classList.contains('nav-open')"):
            page.locator("#mobile-nav-toggle").click()
    elif page.locator("body").evaluate("e=>e.classList.contains('nav-collapsed')"):
        page.locator("#nav-toggle").click()


def select_conversation(page, session_id):
    open_menu(page)
    page.locator(f'.session-item[data-session-id="{session_id}"]').click()
