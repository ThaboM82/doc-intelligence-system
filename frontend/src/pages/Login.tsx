export default function Login() {
  return (
    <div style={{ boxSizing: "border-box", padding: 32, maxWidth: 400, backgroundColor: "#fff", borderRadius: 4, boxShadow: "0 2px 8px rgba(0, 0, 0, 0.15)" }}>
      <label style={{ display: "block", marginBottom: 16 }}>
        Email
        <input type="email" name="email" style={{ boxSizing: "border-box", display: "block", width: "100%", marginTop: 8, padding: 12 }} />
      </label>

      <label style={{ display: "block", marginBottom: 16 }}>
        Password
        <input type="password" name="password" style={{ boxSizing: "border-box", display: "block", width: "100%", marginTop: 8, padding: 12 }} />
      </label>

      <button type="button" style={{ width: "100%", padding: 12, color: "#fff", backgroundColor: "#1976d2", border: 0, borderRadius: 4, cursor: "pointer" }}>
        Sign In
      </button>
    </div>
  );
}