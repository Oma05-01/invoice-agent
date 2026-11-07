from django.urls import path

from vendors.views import VendorListAPIView


urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/vendors/",
        VendorListAPIView.as_view(),
        name="vendor-list",
    ),
]