export type OrganizationMembership = {
  id: string;
  name: string;
  slug: string;
  role: string;
};

export type AuthUser = {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  organizations: OrganizationMembership[];
};

export type AuthStatus =
  | "loading"
  | "authenticated"
  | "unauthenticated";