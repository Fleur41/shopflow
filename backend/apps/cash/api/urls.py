from django.urls import path

from . import views

S = "stores/<uuid:store_id>/"
C = f"{S}cash-sessions/<uuid:session_id>/"

urlpatterns = [
    path(f"{S}tills/", views.TillListView.as_view(), name="till-list"),
    path(f"{S}tills/<uuid:till_id>/", views.TillDetailView.as_view(), name="till-detail"),
    path(f"{S}cash-sessions/", views.SessionListView.as_view(), name="cash-session-list"),
    path(
        f"{S}cash-sessions/current/",
        views.CurrentSessionView.as_view(),
        name="cash-session-current",
    ),
    path(C, views.SessionDetailView.as_view(), name="cash-session-detail"),
    path(f"{C}movements/", views.MovementView.as_view(), name="cash-session-movements"),
    path(f"{C}close/", views.CloseView.as_view(), name="cash-session-close"),
    path(f"{C}corrections/", views.CorrectionView.as_view(), name="cash-session-corrections"),
]
