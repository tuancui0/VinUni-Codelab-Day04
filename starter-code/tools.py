import json
import os
import re
from typing import List, Dict, Any
from datetime import datetime

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "raw-data")

# ---------------------------------------------------------------------------
# Tool #1: search_product_catalog
# TODO: Hoàn thiện hàm này — đọc file product_catalog.json, lọc theo category và max_price.
# ---------------------------------------------------------------------------

def search_product_catalog(category: str, max_price: int = 999999999999) -> List[Dict[str, Any]]:
    """
    Tra cứu sản phẩm/dịch vụ Vingroup theo danh mục và giá tối đa.
    
    Args:
        category: Loại sản phẩm ('xe_dien' hoặc 'du_lich').
        max_price: Giá tối đa (VNĐ). Mặc định không giới hạn.
    
    Returns:
        Danh sách sản phẩm phù hợp điều kiện.
    """
    catalog_file = os.path.join(RAW_DATA_DIR, "product_catalog.json")
    # 1. Kiểm tra file tồn tại
    if not os.path.exists(catalog_file):
        print(f"  Không tìm thấy file catalog: {catalog_file}")
        return []

    # 2. Đọc JSON (bắt lỗi parse + encoding)
    try:
        with open(catalog_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  File catalog không phải JSON hợp lệ: {e}")
        return []
    except OSError as e:
        print(f"  Không đọc được file catalog: {e}")
        return []

    # 3. Chuẩn hóa đầu vào
    if not isinstance(data, list):
        print("  Catalog phải là một danh sách (list), không phải dict.")
        return []

    category_key = category.strip().lower()
    valid_categories = {"xe_dien", "du_lich"}
    if category_key not in valid_categories:
        print(f"  Category '{category}' không hợp lệ. Chỉ chấp nhận: {valid_categories}")
        return []

    try:
        max_price_int = int(max_price)
    except (TypeError, ValueError):
        print(f"  max_price phải là số nguyên, nhận được: {max_price!r}")
        return []

    # 4. Lọc — dùng .get() để không crash nếu record thiếu field
    results: List[Dict[str, Any]] = []
    for p in data:
        if not isinstance(p, dict):
            continue

        p_category = str(p.get("category", "")).strip().lower()
        p_price = p.get("price_vnd")

        # Bỏ qua record thiếu giá hoặc giá không phải số
        if p_price is None:
            continue
        try:
            p_price_int = int(p_price)
        except (TypeError, ValueError):
            continue

        if p_category == category_key and p_price_int <= max_price_int:
            results.append(p)

    # 5. Sắp xếp theo giá tăng dần — hữu ích cho hiển thị
    results.sort(key=lambda x: int(x["price_vnd"]))
    return results
    # TODO: Kiểm tra file tồn tại, đọc JSON, lọc sản phẩm
    # Gợi ý: Lọc theo p["category"] == category AND p["price_vnd"] <= max_price
    return []


# ---------------------------------------------------------------------------
# Tool #2: submit_support_ticket
# TODO: Hoàn thiện hàm này — tạo ticket mới và lưu vào support_tickets.json.
# ---------------------------------------------------------------------------

def submit_support_ticket(
    customer_name: str,
    issue_description: str,
    priority: str = "medium"
) -> Dict[str, Any]:
    """
    Ghi nhận yêu cầu hỗ trợ của khách hàng vào hệ thống ticket.
    
    Args:
        customer_name: Tên khách hàng.
        issue_description: Mô tả vấn đề cần hỗ trợ.
        priority: Mức độ ưu tiên ('low', 'medium', 'high'). Mặc định 'medium'.
    
    Returns:
        Thông tin ticket vừa tạo bao gồm ticket_id, status.
    """
    tickets_file = os.path.join(RAW_DATA_DIR, "support_tickets.json")
    # ── 1. Validate input ─────────────────────────────────────────────
    if not customer_name or not customer_name.strip():
        return {"error": "customer_name không được để trống", "status": "failed"}

    if not issue_description or not issue_description.strip():
        return {"error": "issue_description không được để trống", "status": "failed"}

    valid_priorities = {"low", "medium", "high"}
    priority_key = str(priority).strip().lower() if priority else "medium"
    if priority_key not in valid_priorities:
        # Không raise — hạ về medium và ghi cảnh báo để agent không chết
        priority_key = "medium"

    # ── 2. Load existing tickets ──────────────────────────────────────
    tickets: list = []
    if os.path.exists(tickets_file):
        try:
            with open(tickets_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    tickets = loaded
        except (json.JSONDecodeError, OSError):
            # File hỏng → coi như rỗng, KHÔNG crash agent
            tickets = []

    # ── 3. Sinh ticket_id tuần tự theo ngày ───────────────────────────
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"TK-{today}-"

    # Tìm seq lớn nhất trong các ticket cùng ngày
    max_seq = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for t in tickets:
        tid = str(t.get("ticket_id", "")) if isinstance(t, dict) else ""
        match = pattern.match(tid)
        if match:
            max_seq = max(max_seq, int(match.group(1)))

    new_seq = max_seq + 1
    ticket_id = f"{prefix}{new_seq:03d}"

    # ── 4. Tạo ticket mới ─────────────────────────────────────────────
    new_ticket = {
        "ticket_id": ticket_id,
        "customer_name": customer_name.strip(),
        "issue_description": issue_description.strip(),
        "priority": priority_key,
        "status": "open",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    tickets.append(new_ticket)

    # ── 5. Ghi file an toàn (atomic write) ────────────────────────────
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    tmp_file = tickets_file + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(tickets, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, tickets_file)   # atomic trên POSIX & Windows
    except OSError as e:
        # Dọn file tạm nếu lỗi
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        return {"error": f"Không ghi được file ticket: {e}", "status": "failed"}

    # ── 6. Trả về thông tin ticket vừa tạo ────────────────────────────
    return {
        "ticket_id": ticket_id,
        "status": "open",
        "priority": priority_key,
        "customer_name": new_ticket["customer_name"],
        "created_at": new_ticket["created_at"],
        "message": f"Đã tạo ticket {ticket_id} cho {new_ticket['customer_name']}",
    }
    # TODO: Load existing tickets, generate new ticket_id, append new ticket, save file
    # Gợi ý: ticket_id = f"TK-{today}-{seq:03d}" với today = datetime.now().strftime("%Y%m%d")
    return {"ticket_id": "TODO", "status": "TODO"}


# ---------------------------------------------------------------------------
# TOOL_DEFINITIONS — JSON Schemas mô tả cho LLM
# TODO: Định nghĩa JSON Schema cho từng tool (name, description, parameters).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TOOL_DEFINITIONS — JSON Schemas mô tả cho LLM
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "search_product_catalog",
        "description": (
            "Tra cứu sản phẩm/dịch vụ Vingroup theo danh mục và giá tối đa. "
            "Dùng khi người dùng hỏi về xe điện VinFast, tour/nghỉ dưỡng Vinpearl, "
            "hoặc muốn tìm sản phẩm trong một ngân sách cụ thể."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["xe_dien", "du_lich"],
                    "description": (
                        "Danh mục sản phẩm. 'xe_dien' = xe điện VinFast, "
                        "'du_lich' = tour/nghỉ dưỡng Vinpearl."
                    ),
                },
                "max_price": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 999999999999,
                    "description": (
                        "Giá tối đa tính bằng VNĐ. "
                        "Bỏ trống nếu không giới hạn ngân sách."
                    ),
                },
            },
            "required": ["category"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_support_ticket",
        "description": (
            "Tạo ticket hỗ trợ khách hàng mới. Dùng khi khách hàng báo lỗi sản phẩm, "
            "khiếu nại dịch vụ, hoặc yêu cầu cần nhân viên xử lý."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "Tên đầy đủ của khách hàng.",
                },
                "issue_description": {
                    "type": "string",
                    "minLength": 5,
                    "maxLength": 2000,
                    "description": (
                        "Mô tả chi tiết vấn đề khách hàng gặp phải, "
                        "càng cụ thể càng tốt."
                    ),
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "medium",
                    "description": (
                        "Mức độ ưu tiên. 'high' = khẩn cấp/ảnh hưởng nhiều người, "
                        "'medium' = cần xử lý trong 1-2 ngày, "
                        "'low' = câu hỏi thông thường."
                    ),
                },
            },
            "required": ["customer_name", "issue_description"],
            "additionalProperties": False,
        },
    },
]


# ---------------------------------------------------------------------------
# TOOL_MAP — Ánh xạ tên tool → hàm thực thi
# ---------------------------------------------------------------------------

TOOL_MAP = {
    "search_product_catalog": search_product_catalog,
    "submit_support_ticket": submit_support_ticket
}
