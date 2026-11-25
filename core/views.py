from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .ussd import handle_ussd


def ping(request):
    return JsonResponse({"status": "ok", "service": "somo"})


@csrf_exempt
def ussd(request):
    session_id = request.POST.get("sessionId", "")
    phone_number = request.POST.get("phoneNumber", "")
    service_code = request.POST.get("serviceCode", "")
    text = request.POST.get("text", "")

    response_text = handle_ussd(phone_number, text)

    return HttpResponse(response_text, content_type="text/plain")
