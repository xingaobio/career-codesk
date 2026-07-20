from django.http import HttpResponse
from django.shortcuts import render

from career_codesk.composition import compose_foundation


def home(request):
    """Render the intentionally small, non-operational foundation surface."""
    return render(request, "home.html", {"foundation": compose_foundation()})


def health(request):
    return HttpResponse("ok", content_type="text/plain")
