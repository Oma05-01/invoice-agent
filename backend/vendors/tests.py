from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from organizations.models import (
    Organization,
    OrganizationMembership,
)
from vendors.models import Vendor


User = get_user_model()


class VendorListAPITests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="vendor_test_user",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Vendor Test Company",
            slug="vendor-test-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
            is_active=True,
        )

        self.client.force_authenticate(user=self.user)

        self.url = reverse(
            "vendor-list",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        self.vendor = Vendor.objects.create(
            organization=self.organization,
            legal_name="ABC Engineering Ltd",
            display_name="ABC Engineering",
            vendor_code="ABC-001",
            tax_identification_number="12345678",
            address="14 Industrial Avenue, Ikeja",
            is_active=True,
        )

    def test_active_member_can_list_organization_vendors(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        vendor = response.data["results"][0]

        self.assertEqual(vendor["id"], str(self.vendor.id))
        self.assertEqual(
            vendor["legal_name"],
            "ABC Engineering Ltd",
        )

    def test_inactive_vendors_are_excluded(self):
        Vendor.objects.create(
            organization=self.organization,
            legal_name="Inactive Supplier Ltd",
            is_active=False,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_search_matches_vendor_name(self):
        response = self.client.get(
            self.url,
            {"search": "ABC Engineering"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_search_matches_vendor_tin(self):
        response = self.client.get(
            self.url,
            {"search": "12345678"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_other_organization_vendors_are_excluded(self):
        other_organization = Organization.objects.create(
            name="Another Company",
            slug="another-company",
        )

        Vendor.objects.create(
            organization=other_organization,
            legal_name="External Supplier Ltd",
            is_active=True,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_inactive_member_cannot_list_vendors(self):
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_user_without_membership_cannot_list_vendors(self):
        other_user = User.objects.create_user(
            username="another_vendor_user",
            password="test-password-123",
        )

        self.client.force_authenticate(user=other_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_user_cannot_list_vendors(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_read_only_member_can_list_vendors(self):
        self.membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )
        self.membership.save(update_fields=["role"])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

