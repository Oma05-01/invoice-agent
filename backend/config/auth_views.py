
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import OrganizationMembership


def authenticated_user_data(user):
    """
    Return the authenticated user's profile and active organizations.
    """

    memberships = (
        OrganizationMembership.objects
        .filter(
            user=user,
            is_active=True,
        )
        .select_related("organization")
        .order_by("organization__name")
    )

    organizations = [
        {
            "id": str(membership.organization_id),
            "name": membership.organization.name,
            "slug": membership.organization.slug,
            "role": membership.role,
        }
        for membership in memberships
    ]

    return {
        "id": str(user.pk),
        "username": user.get_username(),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "organizations": organizations,
    }


class CSRFTokenAPIView(APIView):
    """
    Issue a CSRF token before login or other protected requests.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        token = get_token(request._request)

        return Response({
            "csrfToken": token,
        })


@method_decorator(csrf_protect, name="dispatch")
class LoginAPIView(APIView):
    """
    Authenticate a user and establish a Django session.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):

        username = request.data.get("username")
        password = request.data.get("password")

        if (
            not isinstance(username, str)
            or not username.strip()
            or not isinstance(password, str)
            or not password
        ):
            return Response(
                {
                    "detail": "Username and password are required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(
            request._request,
            username=username.strip(),
            password=password,
        )

        if user is None:
            return Response(
                {
                    "detail": "Invalid username or password."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        login(request._request, user)

        return Response({
            "message": "Login successful.",
            "user": authenticated_user_data(user),
            "csrfToken": get_token(request._request),
        })


class LogoutAPIView(APIView):
    """
    End the authenticated user's Django session.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):

        logout(request._request)

        return Response({
            "message": "Logout successful.",
            "csrfToken": get_token(request._request),
        })


class CurrentUserAPIView(APIView):
    """
    Retrieve the current authenticated user's information.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):

        return Response({
            "user": authenticated_user_data(request.user),
        })
