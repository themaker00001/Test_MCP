def process_payment(amount: int, currency: str = "usd"):
    # Mock Stripe response
    return {"status": "succeeded", "id": "ch_mock_123", "amount": amount}