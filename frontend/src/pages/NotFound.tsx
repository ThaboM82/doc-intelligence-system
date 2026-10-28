import {
  Button,
  TextField,
  Paper,
} from "@mui/material";

export default function Login() {
  return (
    <Paper sx={{ p: 4, maxWidth: 400 }}>
      <TextField
        label="Email"
        fullWidth
        margin="normal"
      />

      <TextField
        label="Password"
        type="password"
        fullWidth
        margin="normal"
      />

      <Button
        variant="contained"
        fullWidth
      >
        Sign In
      </Button>
    </Paper>
  );
}