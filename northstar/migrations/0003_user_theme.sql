-- Each user's Light or Dark choice, kept on the server so it follows them between browsers.
ALTER TABLE users ADD COLUMN theme TEXT NOT NULL DEFAULT 'dark' CHECK (theme IN ('light', 'dark'));
