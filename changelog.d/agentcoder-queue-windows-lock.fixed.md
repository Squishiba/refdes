AgentCoder queue state locking now supports Windows through `msvcrt` without
making the queue module's import depend on POSIX `fcntl`.
