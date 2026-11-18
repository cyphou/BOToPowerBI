Option Explicit

' Run inside Desktop Intelligence with the intended document already open.
Public Sub ExportProviderSqlForMigration()
    Dim destination As String
    Dim providers As Object
    Dim provider As Object
    Dim textStream As Object
    Dim byteStream As Object
    Dim providerName As String
    Dim sqlValue As Variant
    Dim sqlText As String
    Dim sqlStatus As String
    Dim failureNumber As Long
    Dim providerError As Long
    Dim i As Long
    Dim result As String

    destination = InputBox("New JSON output path (contains potentially sensitive SQL):")
    If Len(destination) = 0 Then Exit Sub
    On Error GoTo CaptureFailed

    Set providers = Application.ActiveDocument.DataProviders
    result = "["
    For i = 1 To providers.Count
        Set provider = providers.Item(i)
        providerName = provider.Name
        If i > 1 Then result = result & ","

        sqlValue = Empty
        Err.Clear
        On Error Resume Next
        sqlValue = provider.SQL
        providerError = Err.Number
        On Error GoTo CaptureFailed

        sqlText = ""
        If providerError <> 0 Then
            sqlStatus = "unavailable"
        ElseIf VarType(sqlValue) <> vbString Then
            sqlStatus = "unavailable"
        ElseIf Len(Trim$(CStr(sqlValue))) = 0 Then
            sqlStatus = "empty"
        Else
            sqlText = CStr(sqlValue)
            sqlStatus = "captured"
        End If
        result = result & "{""name"":" & DeskIJsonString(providerName) _
            & ",""sql"":" & DeskIJsonString(sqlText) _
            & ",""provider_index"":" & CStr(i) _
            & ",""sql_status"":" & DeskIJsonString(sqlStatus) _
            & ",""sql_error"":" & CStr(providerError) & "}"
    Next i
    result = result & "]"

    Set textStream = CreateObject("ADODB.Stream")
    textStream.Type = 2
    textStream.Charset = "utf-8"
    textStream.Open
    textStream.WriteText result
    textStream.Position = 0
    textStream.Type = 1
    textStream.Position = 3
    Set byteStream = CreateObject("ADODB.Stream")
    byteStream.Type = 1
    byteStream.Open
    textStream.CopyTo byteStream
    byteStream.SaveToFile destination, 1
    byteStream.Close
    textStream.Close
    MsgBox "Provider inventory saved. Review SQL and unavailable providers before use.", vbInformation
    Exit Sub

CaptureFailed:
    failureNumber = Err.Number
    On Error Resume Next
    If Not byteStream Is Nothing Then byteStream.Close
    If Not textStream Is Nothing Then textStream.Close
    On Error GoTo 0
    MsgBox "Provider inventory failed (error " & CStr(failureNumber) _
        & "). Check the document and output path; a partial file may remain.", vbExclamation
End Sub

Private Function DeskIJsonString(ByVal value As String) As String
    Dim i As Long
    Dim character As String
    Dim code As Long
    Dim escaped As String

    For i = 1 To Len(value)
        character = Mid$(value, i, 1)
        code = AscW(character)
        If code < 0 Then code = code + 65536
        If character = Chr$(34) Or character = Chr$(92) Then
            escaped = escaped & Chr$(92) & character
        ElseIf code < 32 Then
            escaped = escaped & "\u" & Right$("000" & Hex$(code), 4)
        Else
            escaped = escaped & character
        End If
    Next i
    DeskIJsonString = Chr$(34) & escaped & Chr$(34)
End Function
