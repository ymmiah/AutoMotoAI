//! Windows caption hit-testing for AutoMoto's own title bar.
//!
//! The web caption uses a fixed contract (also in `app.css` / `dist/app.css`):
//! a 40px bar, a 64px Menu control on the left, and three 46px caption buttons
//! on the right. tao/wry already returns resize-border hits for an undecorated
//! window. This subclass leaves those alone and marks the caption band so a
//! drag or double-click can be handled as a caption. Snap layouts on the
//! maximize control are best-effort; Win+Z and dragging to a screen edge
//! are the snap paths this release relies on.

pub(crate) const CHROME_HEIGHT_PX: f32 = 40.0;
pub(crate) const CHROME_MENU_PX: f32 = 64.0;
pub(crate) const CHROME_BUTTON_PX: f32 = 46.0;

const HTCAPTION: i32 = 2;
const HTMINBUTTON: i32 = 8;
const HTMAXBUTTON: i32 = 9;
const HTCLOSE: i32 = 20;

/// `Some(HT*)` when the point is in the caption band, in client pixels.
/// `None` means the caller should keep the previous hit (client area, menu button, or outside).
#[cfg_attr(all(not(windows), not(test)), allow(dead_code))]
pub(crate) fn caption_hit(x: i32, y: i32, width: i32, dpi: u32) -> Option<i32> {
    if width <= 0 || dpi == 0 || x < 0 || y < 0 {
        return None;
    }
    let scale = dpi as f32 / 96.0;
    let height = (CHROME_HEIGHT_PX * scale).round() as i32;
    if y >= height {
        return None;
    }
    let button = (CHROME_BUTTON_PX * scale).round().max(1.0) as i32;
    let menu = (CHROME_MENU_PX * scale).round().max(1.0) as i32;
    // Caption buttons win on a narrow window so minimize / maximize / close stay hittable.
    if x >= width.saturating_sub(button) {
        Some(HTCLOSE)
    } else if x >= width.saturating_sub(button.saturating_mul(2)) {
        Some(HTMAXBUTTON)
    } else if x >= width.saturating_sub(button.saturating_mul(3)) {
        Some(HTMINBUTTON)
    } else if x < menu {
        None
    } else {
        Some(HTCAPTION)
    }
}

#[cfg(windows)]
pub(crate) fn attach(window: &tauri::WebviewWindow) {
    let Ok(hwnd) = window.hwnd() else { return };
    // HWND is a pointer-sized handle. The subclass only reads geometry.
    let raw = hwnd.0 as isize;
    unsafe {
        SetWindowSubclass(raw, subclass, SUBCLASS_ID, 0);
    }
}

#[cfg(windows)]
const SUBCLASS_ID: usize = 0x4155_544F;

#[cfg(windows)]
const WM_NCHITTEST: u32 = 0x0084;
#[cfg(windows)]
const WM_NCDESTROY: u32 = 0x0082;
#[cfg(windows)]
const HTLEFT: isize = 10;
#[cfg(windows)]
const HTBOTTOMRIGHT: isize = 17;

#[cfg(windows)]
#[repr(C)]
struct Point {
    x: i32,
    y: i32,
}

#[cfg(windows)]
#[repr(C)]
struct Rect {
    left: i32,
    top: i32,
    right: i32,
    bottom: i32,
}

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn ScreenToClient(hwnd: isize, point: *mut Point) -> i32;
    fn GetClientRect(hwnd: isize, rect: *mut Rect) -> i32;
    fn GetDpiForWindow(hwnd: isize) -> u32;
}

#[cfg(windows)]
#[link(name = "comctl32")]
extern "system" {
    fn SetWindowSubclass(
        hwnd: isize,
        callback: unsafe extern "system" fn(isize, u32, usize, isize, usize, usize) -> isize,
        id: usize,
        data: usize,
    ) -> i32;
    fn RemoveWindowSubclass(
        hwnd: isize,
        callback: unsafe extern "system" fn(isize, u32, usize, isize, usize, usize) -> isize,
        id: usize,
    ) -> i32;
    fn DefSubclassProc(hwnd: isize, msg: u32, wparam: usize, lparam: isize) -> isize;
}

#[cfg(windows)]
#[allow(unused_unsafe)]
unsafe extern "system" fn subclass(
    hwnd: isize,
    msg: u32,
    wparam: usize,
    lparam: isize,
    _id: usize,
    _data: usize,
) -> isize {
    if msg == WM_NCDESTROY {
        // SAFETY: comctl32 asks us to drop the subclass while the HWND is still valid.
        unsafe { RemoveWindowSubclass(hwnd, subclass, SUBCLASS_ID) };
        return unsafe { DefSubclassProc(hwnd, msg, wparam, lparam) };
    }
    if msg != WM_NCHITTEST {
        return unsafe { DefSubclassProc(hwnd, msg, wparam, lparam) };
    }
    // SAFETY: lParam is the documented screen point for WM_NCHITTEST. DefSubclassProc
    // forwards to tao, which owns resize-border hits. We only replace client hits
    // inside the caption band.
    let prior = unsafe { DefSubclassProc(hwnd, msg, wparam, lparam) };
    if (HTLEFT..=HTBOTTOMRIGHT).contains(&prior) {
        return prior;
    }
    let mut point = Point {
        x: lparam as i16 as i32,
        y: (lparam >> 16) as i16 as i32,
    };
    let mut rect = Rect {
        left: 0,
        top: 0,
        right: 0,
        bottom: 0,
    };
    let mapped = unsafe { ScreenToClient(hwnd, &mut point) };
    let sized = unsafe { GetClientRect(hwnd, &mut rect) };
    if mapped == 0 || sized == 0 {
        return prior;
    }
    let dpi = unsafe { GetDpiForWindow(hwnd) }.max(96);
    match caption_hit(point.x, point.y, rect.right - rect.left, dpi) {
        Some(hit) => hit as isize,
        None => prior,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn caption_zones_follow_the_css_contract_at_96_dpi() {
        assert_eq!(
            caption_hit(10, 8, 1000, 96),
            None,
            "menu stays a client click"
        );
        assert_eq!(caption_hit(63, 8, 1000, 96), None);
        assert_eq!(caption_hit(64, 8, 1000, 96), Some(HTCAPTION));
        assert_eq!(caption_hit(861, 39, 1000, 96), Some(HTCAPTION));
        assert_eq!(caption_hit(862, 8, 1000, 96), Some(HTMINBUTTON));
        assert_eq!(caption_hit(907, 8, 1000, 96), Some(HTMINBUTTON));
        assert_eq!(caption_hit(908, 8, 1000, 96), Some(HTMAXBUTTON));
        assert_eq!(caption_hit(953, 8, 1000, 96), Some(HTMAXBUTTON));
        assert_eq!(caption_hit(954, 8, 1000, 96), Some(HTCLOSE));
        assert_eq!(caption_hit(999, 0, 1000, 96), Some(HTCLOSE));
        assert_eq!(caption_hit(200, 40, 1000, 96), None);
        assert_eq!(caption_hit(-1, 8, 1000, 96), None);
        assert_eq!(caption_hit(8, 8, 0, 96), None);
        assert_eq!(caption_hit(8, 8, 1000, 0), None);
    }

    #[test]
    fn caption_zones_scale_with_dpi() {
        assert_eq!(
            caption_hit(100, 79, 2000, 192),
            None,
            "menu is 128px at 200%"
        );
        assert_eq!(caption_hit(128, 79, 2000, 192), Some(HTCAPTION));
        assert_eq!(caption_hit(1724, 10, 2000, 192), Some(HTMINBUTTON));
        assert_eq!(caption_hit(1816, 10, 2000, 192), Some(HTMAXBUTTON));
        assert_eq!(caption_hit(1908, 10, 2000, 192), Some(HTCLOSE));
        assert_eq!(caption_hit(400, 80, 2000, 192), None);
    }
}
