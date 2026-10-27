import api from "./api";

export const UploadService = {
  uploadDocument: async (
    file: File
  ) => {
    const formData =
      new FormData();

    formData.append(
      "file",
      file
    );

    const response =
      await fetch(
        `${
          import.meta.env
            .VITE_API_URL
        }/upload`,
        {
          method: "POST",
          body: formData,
        }
      );

    return response.json();
  },
};