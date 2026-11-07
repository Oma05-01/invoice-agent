
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import type { AuthUser, AuthStatus } from "@/types/auth";

type AuthContextValue = {
  user: AuthUser | null;
  status: AuthStatus;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

type CSRFResponse = {
  csrfToken: string;
};

type LoginResponse = {
  message: string;
  user: AuthUser;
  csrfToken: string;
};

type CurrentUserResponse = {
  user: AuthUser;
};

const AuthContext = createContext<AuthContextValue | undefined>(
  undefined,
);

async function getCSRFToken(): Promise<string> {
  const response = await fetch("/api/auth/csrf/", {
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Unable to establish a secure connection.");
  }

  const data: CSRFResponse = await response.json();

  return data.csrfToken;
}

async function getErrorMessage(response: Response): Promise<string> {
  const data = await response.json().catch(() => ({}));

  if (typeof data.detail === "string") {
    return data.detail;
  }

  if (typeof data.message === "string") {
    return data.message;
  }

  for (const value of Object.values(data)) {
    if (typeof value === "string") return value;

    if (Array.isArray(value) && typeof value[0] === "string") {
      return value[0];
    }
  }

  return `Request failed with status ${response.status}.`;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [csrfToken, setCsrfToken] = useState<string | null>(null);

  // Restore an existing Django session after page reload.
  useEffect(() => {
    const controller = new AbortController();

    async function restoreSession() {
      try {
        const tokenResponse = await fetch("/api/auth/csrf/", {
          credentials: "same-origin",
          cache: "no-store",
          signal: controller.signal,
        });

        if (!tokenResponse.ok) {
          throw new Error("Unable to initialise authentication.");
        }

        const tokenData: CSRFResponse = await tokenResponse.json();

        setCsrfToken(tokenData.csrfToken);

        const response = await fetch("/api/auth/me/", {
          credentials: "same-origin",
          cache: "no-store",
          signal: controller.signal,
        });

        if (response.status === 401 || response.status === 403) {
          setUser(null);
          setStatus("unauthenticated");
          return;
        }

        if (!response.ok) {
          throw new Error("Unable to retrieve your account.");
        }

        const data: CurrentUserResponse = await response.json();

        setUser(data.user);
        setStatus("authenticated");
      } catch (error) {
        if (controller.signal.aborted) return;

        console.error("Session restoration failed:", error);

        setUser(null);
        setStatus("unauthenticated");
      }
    }

    restoreSession();

    return () => controller.abort();
  }, []);

  const login = useCallback(
    async (username: string, password: string) => {
      const token = await getCSRFToken();

      setCsrfToken(token);

      const response = await fetch("/api/auth/login/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": token,
        },
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      const data: LoginResponse = await response.json();

      setCsrfToken(data.csrfToken);
      setUser(data.user);
      setStatus("authenticated");
    },
    [],
  );

  const logout = useCallback(async () => {
    const token = csrfToken || await getCSRFToken();

    const response = await fetch("/api/auth/logout/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": token,
      },
    });

    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }

    const data: CSRFResponse = await response.json();

    setCsrfToken(data.csrfToken);
    setUser(null);
    setStatus("unauthenticated");
  }, [csrfToken]);

  return (
    <AuthContext.Provider value={{ user, status, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }

  return context;
}
