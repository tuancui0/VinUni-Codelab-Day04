"""
Lab #4: System Prompt Engineering & Tool Calling Engine
Học viên hoàn thiện các mục TODO để hoàn thành bài lab.

Kiến trúc:
  - ChatbotBaseline: LLM thuần, không dùng tool → quan sát hallucination.
  - ToolCallingAgent: Agent dùng System Prompt + 2 Tool Schemas.
"""

import json
import re
import unicodedata
from typing import Dict, Any, List
from tools import TOOL_DEFINITIONS, TOOL_MAP, search_product_catalog, submit_support_ticket

# ═══════════════════════════════════════════════════════════════════════════
# TODO 1: Thiết kế SYSTEM PROMPT cấp sản xuất
# Yêu cầu: Phải chứa Persona, Core Rules, Operational Boundaries, Output Contract.
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Bạn là VinAssistant — trợ lý AI chính thức của hệ sinh thái Vingroup.

## PERSONA
- Tên: VinAssistant
- Vai trò: Chuyên viên tư vấn sản phẩm & dịch vụ Vingroup (VinFast, Vinpearl)
- Giọng nói: Chuyên nghiệp, thân thiện, chính xác, không bịa thông tin.

## AVAILABLE TOOLS
{tools}

## CORE RULES (Bắt buộc tuân thủ)
1. KHÔNG BAO GIỜ bịa dữ liệu sản phẩm (giá, tính năng, tồn kho). PHẢI gọi tool `search_product_catalog` để lấy dữ liệu thực.
2. KHÔNG BAO GIỜ tự tạo ticket_id. PHẢI gọi tool `submit_support_ticket` để hệ thống tự sinh.
3. Nếu khách hàng hỏi câu FAQ đơn giản (chính sách bảo hành, đổi trả), trả lời trực tiếp KHÔNG cần gọi tool.
4. Nếu câu hỏi cần NHIỀU tool, hãy gọi TUẦN TỰ từng tool rồi tổng hợp kết quả cuối cùng.

## OPERATIONAL BOUNDARIES
- Chỉ trả lời về sản phẩm/dịch vụ thuộc hệ sinh thái Vingroup.
- Từ chối lịch sự nếu câu hỏi ngoài phạm vi (tiền điện tử, chính trị, v.v.).

## OUTPUT CONTRACT
- Luôn trả lời bằng tiếng Việt.
- Khi liệt kê sản phẩm, dùng bảng hoặc danh sách có thứ tự.
- Khi tạo ticket, xác nhận lại ticket_id và mức ưu tiên cho khách hàng.

## RESPONSE FORMAT (cho mỗi bước suy luận)
Thought: <suy nghĩ bước này>
Action: {{"name": "<tên tool>", "args": {{<các tham số>}}}}
Observation: <kết quả trả về từ tool>
... (Lặp lại nếu cần thêm tool)
Final Answer: <câu trả lời hoàn chỉnh cho khách hàng>
""".format(tools=json.dumps(TOOL_DEFINITIONS, ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════════════════════════════
# CLASS: ChatbotBaseline
# ═══════════════════════════════════════════════════════════════════════════

class ChatbotBaseline:
    """Baseline LLM Chatbot — Không sử dụng Tool Calling hay ReAct Loop."""

    def query(self, user_input: str) -> Dict[str, Any]:
        # TODO 2: Trả về câu trả lời tĩnh (mock) hoặc gọi Gemini API 1 lượt (không dùng tool)
        # Mục tiêu: Quan sát hiện tượng bịa thông tin (hallucination)
        return {
            "answer": f"[Chatbot Baseline] Trả lời cho: {user_input}",
            "tool_calls": [],
            "status": "success",
            "mode": "mock_baseline"
        }


# ═══════════════════════════════════════════════════════════════════════════
# CLASS: ToolCallingAgent
# ═══════════════════════════════════════════════════════════════════════════

class ToolCallingAgent:
    """Agent với System Prompt Engineering & Tool Calling."""

    def __init__(self, max_iterations: int = 5):
        if max_iterations < 1:
            raise ValueError("max_iterations phải lớn hơn hoặc bằng 1")
        self.max_iterations = max_iterations
        self.trace: List[Dict[str, Any]] = []

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFD", text.lower())
        without_marks = "".join(
            char for char in normalized if unicodedata.category(char) != "Mn"
        )
        return without_marks.replace("đ", "d")

    @classmethod
    def _detect_intents(cls, user_input: str) -> Dict[str, Any]:
        text = cls._normalize(user_input)
        has_vehicle = any(term in text for term in ("vinfast", "xe dien", "xe ", "oto", "o to"))
        has_travel = any(
            term in text
            for term in ("vinpearl", "du lich", "nghi duong", "resort", "tour")
        )
        wants_catalog = any(
            term in text
            for term in (
                "gia",
                "ngan sach",
                "duoi ",
                "tren ",
                "xem ",
                "tim ",
                "goi y",
                "liet ke",
                "mua ",
                "co mau nao",
                "co xe nao",
                "co goi nao",
                "catalog",
            )
        )
        needs_catalog = (has_vehicle or has_travel) and wants_catalog

        ticket_terms = (
            "bao loi",
            "bi loi",
            "hong",
            "su co",
            "khieu nai",
            "can ho tro",
            "tao ticket",
            "lap ticket",
            "yeu cau ho tro",
        )
        needs_ticket = any(term in text for term in ticket_terms)
        faq_terms = ("bao hanh", "doi tra", "hoan tien", "chinh sach")
        is_faq = any(term in text for term in faq_terms)

        if "du lich" in text or "vinpearl" in text or any(
            term in text for term in ("resort", "tour", "nghi duong")
        ):
            category = "du_lich"
        elif has_vehicle:
            category = "xe_dien"
        else:
            category = None

        return {
            "needs_catalog": needs_catalog,
            "needs_ticket": needs_ticket,
            "is_faq": is_faq,
            "category": category,
            "max_price": cls._extract_max_price(text),
        }

    @staticmethod
    def _extract_max_price(text: str):
        patterns = (
            (r"(\d+(?:[.,]\d+)?)\s*(?:ty|billion|bn)\b", 1_000_000_000),
            (r"(\d+(?:[.,]\d+)?)\s*(?:trieu|tr|million)\b", 1_000_000),
        )
        for pattern, multiplier in patterns:
            match = re.search(pattern, text)
            if match:
                amount = float(match.group(1).replace(",", "."))
                return int(amount * multiplier)

        currency_match = re.search(r"(\d[\d.,]*)\s*(?:vnd|vnđ|dong)\b", text)
        if currency_match:
            return int(re.sub(r"[.,]", "", currency_match.group(1)))

        grouped_match = re.search(r"(?<!\w)(\d{1,3}(?:[.,]\d{3})+)(?!\w)", text)
        if grouped_match:
            return int(re.sub(r"[.,]", "", grouped_match.group(1)))

        plain_match = re.search(r"(?<!\w)(\d{7,})(?!\w)", text)
        return int(plain_match.group(1)) if plain_match else None

    @staticmethod
    def _extract_customer_name(user_input: str):
        match = re.search(
            r"\b(?:tôi tên là|tôi tên|tên tôi là|em tên là|anh tên là|chị tên là|tôi là)"
            r"\s+([^,.;!?\n]+)",
            user_input,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip() if match else None

    @classmethod
    def _infer_priority(cls, user_input: str) -> str:
        text = cls._normalize(user_input)
        if any(term in text for term in ("khong gap", "khong khan", "uu tien thap")):
            return "low"
        if any(term in text for term in ("gap", "khan cap", "nghiem trong", "anh huong")):
            return "high"
        return "medium"

    @staticmethod
    def _format_products(products: List[Dict[str, Any]]) -> str:
        if not products:
            return "Rất tiếc, không tìm thấy sản phẩm phù hợp với tiêu chí của bạn."

        lines = ["Các sản phẩm phù hợp:"]
        for product in products:
            price = f"{int(product['price_vnd']):,}".replace(",", ".")
            description = product.get("description", "")
            lines.append(f"- {product['name']} — {price} VNĐ. {description}".rstrip())
        return "\n".join(lines)

    @staticmethod
    def _faq_answer(user_input: str) -> str:
        text = ToolCallingAgent._normalize(user_input)
        if "bao hanh" in text:
            return (
                "Danh mục hiện có ghi nhận VinFast VF 5 Plus được bảo hành pin 10 năm. "
                "Thời hạn và điều kiện có thể khác theo từng mẫu xe; vui lòng kiểm tra "
                "chính sách chính thức cho mẫu xe cụ thể."
            )
        return (
            "Mình chưa có đủ thông tin chính thức về chính sách này trong danh mục hiện tại. "
            "Bạn vui lòng kiểm tra điều khoản của dịch vụ hoặc liên hệ kênh hỗ trợ chính thức "
            "của Vingroup."
        )

    def run(self, user_input: str) -> Dict[str, Any]:
        """Điểm vào chính — chạy Agent Loop."""
        self.trace = []
        self.trace.append({"step": "init", "user_input": user_input})

        intents = self._detect_intents(user_input)
        self.trace.append({"step": "intent_detection", "intents": intents})

        actions = []
        if intents["needs_catalog"] and intents["category"]:
            args = {"category": intents["category"]}
            if intents["max_price"] is not None:
                args["max_price"] = intents["max_price"]
            actions.append(("search_product_catalog", args))

        customer_name = self._extract_customer_name(user_input)
        if intents["needs_ticket"] and customer_name:
            actions.append(
                (
                    "submit_support_ticket",
                    {
                        "customer_name": customer_name,
                        "issue_description": user_input.strip(),
                        "priority": self._infer_priority(user_input),
                    },
                )
            )

        observations = []
        for iteration, (tool_name, args) in enumerate(actions, start=1):
            if iteration > self.max_iterations:
                answer = (
                    "Yêu cầu cần nhiều bước hơn giới hạn xử lý hiện tại. "
                    "Vui lòng gửi lại yêu cầu để tiếp tục."
                )
                self.trace.append({"step": "max_iterations_reached", "limit": self.max_iterations})
                self.trace.append({"step": "final_answer", "answer": answer})
                return {
                    "answer": answer,
                    "trace": self.trace,
                    "iterations": self.max_iterations,
                    "status": "max_iterations_reached",
                }

            self.trace.append(
                {
                    "step": "tool_call",
                    "iteration": iteration,
                    "name": tool_name,
                    "args": args,
                }
            )
            result = TOOL_MAP[tool_name](**args)
            self.trace.append(
                {
                    "step": "observation",
                    "iteration": iteration,
                    "name": tool_name,
                    "result": result,
                }
            )
            observations.append((tool_name, result))

        if actions and len(observations) < len(actions):
            answer = "Không thể hoàn tất toàn bộ yêu cầu trong giới hạn số bước."
            status = "max_iterations_reached"
            iterations = self.max_iterations
        elif observations:
            answer_parts = []
            status = "completed"
            for tool_name, result in observations:
                if tool_name == "search_product_catalog":
                    answer_parts.append(self._format_products(result))
                elif result.get("status") == "failed" or result.get("error"):
                    answer_parts.append(
                        f"Không thể tạo yêu cầu hỗ trợ: {result.get('error', 'lỗi không xác định')}."
                    )
                    status = "failed"
                else:
                    answer_parts.append(
                        f"Đã tạo ticket {result['ticket_id']} cho {result['customer_name']} "
                        f"(mức ưu tiên: {result['priority']})."
                    )
            if intents["needs_ticket"] and not customer_name:
                answer_parts.append("Để tạo ticket, vui lòng cho mình biết tên của bạn.")
            answer = "\n".join(answer_parts)
            iterations = len(observations)
        elif intents["needs_ticket"] and not customer_name:
            answer = "Để tạo yêu cầu hỗ trợ, vui lòng cho mình biết tên của bạn."
            status = "completed"
            iterations = 1
        elif intents["is_faq"]:
            answer = self._faq_answer(user_input)
            status = "completed"
            iterations = 1
        else:
            answer = (
                "Mình có thể hỗ trợ tra cứu xe điện VinFast, dịch vụ Vinpearl hoặc ghi nhận "
                "yêu cầu hỗ trợ. Bạn muốn tìm hiểu nội dung nào?"
            )
            status = "completed"
            iterations = 1

        self.trace.append({"step": "final_answer", "answer": answer})
        return {
            "answer": answer,
            "trace": self.trace,
            "iterations": iterations,
            "status": status,
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAIN — Chạy thử nhanh
# ═══════════════════════════════════════════════════════════════════════════

def main():
    user_query = "Tôi muốn xem xe điện VinFast giá dưới 600 triệu."

    print("=== RUNNING CHATBOT BASELINE ===")
    chatbot = ChatbotBaseline()
    print(chatbot.query(user_query))

    print("\n=== RUNNING TOOL CALLING AGENT ===")
    agent = ToolCallingAgent(max_iterations=5)
    result = agent.run(user_query)
    print("Result:", result["answer"])
    print("Trace Log:", json.dumps(agent.trace, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
